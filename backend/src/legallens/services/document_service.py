"""Documents: upload, library, status, page preview, retry and delete (FR-1 to FR-5, FR-21)."""

import asyncio

import structlog
from sqlalchemy import func, select, text, update

from legallens.config import Settings
from legallens.db.engine import Database
from legallens.db.models import ConversationRow, DocumentPageRow, DocumentRow
from legallens.errors import DOCUMENT_NOT_FOUND, conflict, not_found, unprocessable
from legallens.ids import new_id, now_iso
from legallens.ingestion.job_runner import IngestionRunner
from legallens.ingestion.validation import clean_display_name, inspect_file
from legallens.logging import timed
from legallens.ports.ingestion import IngestionPipeline
from legallens.services.transaction_logger import TransactionLogger
from legallens.storage.file_store import AsyncReadable, FileStore

log = structlog.get_logger("legallens.documents")


class DocumentService:
    def __init__(
        self,
        db: Database,
        files: FileStore,
        runner: IngestionRunner,
        pipeline: IngestionPipeline,
        tx: TransactionLogger,
        settings: Settings,
    ) -> None:
        self._db = db
        self._files = files
        self._runner = runner
        self._pipeline = pipeline
        self._tx = tx
        self._settings = settings

    # ------------------------------------------------------------ queries

    async def list(self) -> list[DocumentRow]:
        async with self._db.session() as s:
            rows = await s.scalars(
                select(DocumentRow).order_by(DocumentRow.uploaded_at.desc(), DocumentRow.id)
            )
            return list(rows.all())

    async def get(self, document_id: str) -> DocumentRow:
        async with self._db.session() as s:
            doc = await s.get(DocumentRow, document_id)
        if doc is None:
            raise not_found("document_not_found", DOCUMENT_NOT_FOUND)
        return doc

    async def page(self, document_id: str, number: int) -> tuple[DocumentRow, DocumentPageRow]:
        async with self._db.session() as s:
            doc = await s.get(DocumentRow, document_id)
            if doc is None:
                raise not_found("document_not_found", DOCUMENT_NOT_FOUND)
            if doc.status != "ready":
                raise conflict(
                    "document_not_ready",
                    "This document is not ready yet. Wait for processing to finish.",
                )
            page = await s.get(DocumentPageRow, (document_id, number))
        if page is None:
            raise not_found("page_not_found", f"Page {number} does not exist in this document.")
        return doc, page

    # ------------------------------------------------------------ commands

    async def upload(self, source: AsyncReadable, filename: str | None) -> DocumentRow:
        async with self._tx.track("document.upload") as tracked:
            received = await self._files.receive(source, self._settings.max_upload_bytes)
            stored_as: str | None = None
            try:
                if received.size == 0:
                    raise unprocessable("empty_file", "This file is empty.")
                with timed("upload.inspect"):
                    info = await asyncio.to_thread(
                        inspect_file, received.path, filename or "", self._settings.max_pages
                    )
                name = clean_display_name(filename, info.type)

                async with self._db.session() as s:
                    if await s.scalar(
                        select(DocumentRow.id).where(DocumentRow.sha256 == received.sha256)
                    ):
                        raise conflict(
                            "duplicate_document", "This file is already in your library."
                        )
                    count = await s.scalar(select(func.count()).select_from(DocumentRow)) or 0
                    if count >= self._settings.max_documents:
                        raise conflict(
                            "library_full",
                            f"Your library is full ({self._settings.max_documents} documents). "
                            "Delete a document to upload another.",
                        )
                    now = now_iso()
                    doc = DocumentRow(
                        id=new_id("doc"),
                        name=name,
                        type=info.type,
                        size_bytes=received.size,
                        sha256=received.sha256,
                        pages=info.pages,
                        is_scanned=False,
                        status="processing",
                        stage="validating",
                        progress_current=None,
                        progress_total=None,
                        warnings=[],
                        error=None,
                        uploaded_at=now,
                        updated_at=now,
                    )
                    self._files.commit(received.path, doc.id, info.type)
                    stored_as = doc.id
                    s.add(doc)
            except BaseException:
                self._files.discard(received.path)
                if stored_as is not None:  # the DB insert failed after the file was moved
                    self._files.delete_document(stored_as)
                raise
            tracked.entity_id = doc.id

        await self._runner.enqueue(doc.id)
        log.info("document_uploaded", document_id=doc.id, type=doc.type, size=doc.size_bytes)
        return doc

    async def retry(self, document_id: str) -> DocumentRow:
        async with self._tx.track("document.retry", document_id):
            async with self._db.session() as s:
                doc = await s.get(DocumentRow, document_id)
                if doc is None:
                    raise not_found("document_not_found", DOCUMENT_NOT_FOUND)
                if doc.status != "failed":
                    raise conflict("document_not_failed", "Only failed documents can be retried.")
                doc.status, doc.stage, doc.error = "processing", "validating", None
                doc.progress_current = doc.progress_total = None
                doc.updated_at = now_iso()
            await self._runner.enqueue(document_id)
            return doc

    async def delete(self, document_id: str) -> None:
        """Removes the file, page text, chunks, keyword index rows and vectors (FR-5).
        Conversations that used the document stay, marked ``documentDeleted`` (FR-21)."""
        async with self._tx.track("document.delete", document_id):
            await self.get(document_id)
            await self._runner.cancel(document_id)
            await self._pipeline.purge(document_id)
            async with self._db.session() as s:
                doc = await s.get(DocumentRow, document_id)
                if doc is None:
                    raise not_found("document_not_found", DOCUMENT_NOT_FOUND)
                await s.execute(
                    text("DELETE FROM chunks_fts WHERE document_id = :id"), {"id": document_id}
                )
                await s.delete(doc)  # pages, chunks and jobs cascade
                await s.execute(
                    update(ConversationRow)
                    .where(ConversationRow.document_id == document_id)
                    .values(document_deleted=True)
                )
            await asyncio.to_thread(self._files.delete_document, document_id)
        log.info("document_deleted", document_id=document_id)
