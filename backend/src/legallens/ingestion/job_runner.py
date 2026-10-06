"""Background ingestion queue (FR-3, NFR-8).

One worker processes documents one at a time. Each job calls the configured
``IngestionPipeline``, retries transient failures with backoff, and always ends with the
document Ready or Failed, so nothing is left half-processed. Documents still Processing
after a crash or restart are re-queued on startup.
"""

import asyncio
import contextlib
import time

import structlog
from sqlalchemy import delete, select, update

from legallens.config import Settings
from legallens.db.engine import Database
from legallens.db.models import DocumentPageRow, DocumentRow, IngestionJobRow
from legallens.ids import new_id, now_iso
from legallens.logging import timed
from legallens.ports.ingestion import (
    IngestionFailed,
    IngestionInput,
    IngestionPipeline,
    IngestionResult,
    IngestionStage,
)
from legallens.storage.file_store import FileStore

log = structlog.get_logger("legallens.ingestion")

PROGRESS_MIN_INTERVAL_S = 0.5


class _ProgressWriter:
    """Writes live stage/page progress to the document row, at most ~2 writes per second."""

    def __init__(self, db: Database, document_id: str) -> None:
        self._db = db
        self._document_id = document_id
        self._last_stage: str | None = None
        self._last_write = 0.0

    async def __call__(
        self, stage: IngestionStage, current: int | None = None, total: int | None = None
    ) -> None:
        now = time.monotonic()
        is_last_page = current is not None and current == total
        if (
            stage == self._last_stage
            and not is_last_page
            and now - self._last_write < PROGRESS_MIN_INTERVAL_S
        ):
            return
        self._last_stage, self._last_write = stage, now
        async with self._db.session() as s:
            await s.execute(
                update(DocumentRow)
                .where(DocumentRow.id == self._document_id, DocumentRow.status == "processing")
                .values(
                    stage=stage,
                    progress_current=current,
                    progress_total=total,
                    updated_at=now_iso(),
                )
            )


class IngestionRunner:
    def __init__(
        self, db: Database, pipeline: IngestionPipeline, files: FileStore, settings: Settings
    ) -> None:
        self._db = db
        self._pipeline = pipeline
        self._files = files
        self._settings = settings
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._cancelled: set[str] = set()
        self._current: tuple[str, asyncio.Task[None]] | None = None
        self._worker: asyncio.Task[None] | None = None

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        if self._worker is None:
            self._worker = asyncio.create_task(self._work(), name="ingestion-worker")

    async def stop(self) -> None:
        """Stops the worker. An interrupted job stays Processing and is re-queued next start."""
        if self._worker is not None:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
            self._worker = None

    async def recover(self) -> int:
        """Re-queues documents left Processing by a crash or restart."""
        async with self._db.session() as s:
            await s.execute(
                update(IngestionJobRow)
                .where(IngestionJobRow.state.in_(("queued", "running")))
                .values(state="cancelled", finished_at=now_iso(), error="interrupted by restart")
            )
            ids = list(
                (
                    await s.scalars(
                        select(DocumentRow.id)
                        .where(DocumentRow.status == "processing")
                        .order_by(DocumentRow.uploaded_at)
                    )
                ).all()
            )
            await s.execute(
                update(DocumentRow)
                .where(DocumentRow.id.in_(ids))
                .values(stage="validating", progress_current=None, progress_total=None)
            )
        for document_id in ids:
            await self.enqueue(document_id)
        if ids:
            log.info("ingestion_recovered", count=len(ids))
        return len(ids)

    async def wait_idle(self) -> None:
        """Waits until every queued job has finished (used by tests and the demo seeder)."""
        await self._queue.join()

    # ------------------------------------------------------------ commands

    async def enqueue(self, document_id: str) -> None:
        async with self._db.session() as s:
            s.add(
                IngestionJobRow(
                    id=new_id("job"),
                    document_id=document_id,
                    state="queued",
                    created_at=now_iso(),
                )
            )
        self._cancelled.discard(document_id)
        await self._queue.put(document_id)

    async def cancel(self, document_id: str) -> None:
        """Drops a queued job, or stops the running one (used before deleting a document)."""
        self._cancelled.add(document_id)
        current = self._current
        if current is not None and current[0] == document_id:
            current[1].cancel()
            await asyncio.wait({current[1]})

    # ------------------------------------------------------------ worker

    async def _work(self) -> None:
        while True:
            document_id = await self._queue.get()
            try:
                if document_id in self._cancelled:
                    continue
                task = asyncio.create_task(self._process(document_id))
                self._current = (document_id, task)
                try:
                    await task
                except asyncio.CancelledError:
                    worker = asyncio.current_task()
                    if worker is not None and worker.cancelling():
                        raise  # the worker itself is shutting down
                    # otherwise only this job was cancelled (its document is being deleted)
                except Exception:
                    log.exception("ingestion_job_crashed", document_id=document_id)
            finally:
                self._current = None
                self._queue.task_done()

    async def _process(self, document_id: str) -> None:
        async with self._db.session() as s:
            doc = await s.get(DocumentRow, document_id)
            if doc is None or doc.status != "processing":
                return
            job = await s.scalar(
                select(IngestionJobRow)
                .where(IngestionJobRow.document_id == document_id)
                .order_by(IngestionJobRow.created_at.desc())
                .limit(1)
            )
            if job is None:
                return
            job.state, job.started_at = "running", now_iso()
            job_id = job.id
            item = IngestionInput(
                document_id=doc.id,
                name=doc.name,
                type="pdf" if doc.type == "pdf" else "docx",
                path=self._files.path_for(doc.id, doc.type),
                pages=doc.pages,
            )

        max_attempts = 1 + self._settings.ingestion_max_retries
        progress = _ProgressWriter(self._db, document_id)
        with structlog.contextvars.bound_contextvars(document_id=document_id, job_id=job_id):
            for attempt in range(1, max_attempts + 1):
                await self._set_job(job_id, attempts=attempt)
                try:
                    with timed("ingestion.run", attempt=attempt):
                        async with asyncio.timeout(self._settings.ingestion_timeout_s):
                            result = await self._pipeline.run(item, progress)
                except IngestionFailed as exc:
                    if exc.retryable and attempt < max_attempts:
                        await self._backoff(attempt)
                        continue
                    await self._fail(document_id, job_id, exc.user_message)
                    return
                except TimeoutError:
                    await self._fail(
                        document_id,
                        job_id,
                        "Processing took too long and was stopped. Retry, or split the "
                        "document into smaller files.",
                    )
                    return
                except Exception as exc:
                    log.warning(
                        "ingestion_attempt_failed", attempt=attempt, error=type(exc).__name__
                    )
                    if attempt < max_attempts:
                        await self._backoff(attempt)
                        continue
                    await self._fail(
                        document_id,
                        job_id,
                        f"Processing failed after {attempt} attempts. Retry, or delete the "
                        "document.",
                    )
                    return
                await self._succeed(document_id, job_id, result)
                return

    async def _backoff(self, attempt: int) -> None:
        await asyncio.sleep(self._settings.ingestion_retry_backoff_s * 2 ** (attempt - 1))

    async def _set_job(self, job_id: str, **values: object) -> None:
        async with self._db.session() as s:
            await s.execute(
                update(IngestionJobRow).where(IngestionJobRow.id == job_id).values(**values)
            )

    async def _succeed(self, document_id: str, job_id: str, result: IngestionResult) -> None:
        if not any(page.paragraphs for page in result.pages):
            await self._fail(document_id, job_id, "No text could be extracted from this document.")
            return
        async with self._db.session() as s:
            doc = await s.get(DocumentRow, document_id)
            if doc is None:
                return
            await s.execute(
                delete(DocumentPageRow).where(DocumentPageRow.document_id == document_id)
            )
            s.add_all(
                DocumentPageRow(
                    document_id=document_id,
                    page=page.page,
                    section=page.section,
                    paragraphs=page.paragraphs,
                    ocr=page.ocr,
                    ocr_confidence=page.ocr_confidence,
                )
                for page in result.pages
            )
            doc.pages = len(result.pages)
            doc.is_scanned = result.is_scanned
            doc.warnings = list(result.warnings)
            doc.status, doc.stage, doc.error = "ready", None, None
            doc.progress_current = doc.progress_total = None
            doc.updated_at = now_iso()
            await s.execute(
                update(IngestionJobRow)
                .where(IngestionJobRow.id == job_id)
                .values(state="succeeded", finished_at=now_iso(), error=None)
            )
        log.info("ingestion_ready", pages=len(result.pages), warnings=len(result.warnings))

    async def _fail(self, document_id: str, job_id: str, message: str) -> None:
        async with self._db.session() as s:
            await s.execute(
                update(DocumentRow)
                .where(DocumentRow.id == document_id)
                .values(
                    status="failed",
                    stage=None,
                    progress_current=None,
                    progress_total=None,
                    error=message,
                    updated_at=now_iso(),
                )
            )
            await s.execute(
                update(IngestionJobRow)
                .where(IngestionJobRow.id == job_id)
                .values(state="failed", finished_at=now_iso(), error=message)
            )
        log.info("ingestion_failed")
