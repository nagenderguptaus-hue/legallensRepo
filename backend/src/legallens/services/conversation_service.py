"""Conversations: list, create, open, rename, re-link and delete (FR-19, FR-20)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from legallens.db.engine import Database
from legallens.db.models import ConversationRow, DocumentRow, MessageRow
from legallens.errors import (
    CONVERSATION_NOT_FOUND,
    DOCUMENT_NOT_FOUND,
    not_found,
    unprocessable,
)
from legallens.ids import new_id, now_iso
from legallens.services.transaction_logger import TransactionLogger

DEFAULT_TITLE = "New conversation"
MAX_TITLE_CHARS = 120

UNSET = object()


def clean_title(raw: str) -> str:
    title = " ".join(raw.split())
    if not title:
        raise unprocessable("invalid_title", "Title cannot be empty.")
    return title[:MAX_TITLE_CHARS]


async def _ensure_document(s: AsyncSession, document_id: str | None) -> None:
    if document_id is not None and await s.get(DocumentRow, document_id) is None:
        raise not_found("document_not_found", DOCUMENT_NOT_FOUND)


class ConversationService:
    def __init__(self, db: Database, tx: TransactionLogger) -> None:
        self._db = db
        self._tx = tx

    async def list(self) -> list[ConversationRow]:
        async with self._db.session() as s:
            rows = await s.scalars(
                select(ConversationRow).order_by(
                    ConversationRow.updated_at.desc(), ConversationRow.id
                )
            )
            return list(rows.all())

    async def get_detail(self, conversation_id: str) -> ConversationRow:
        async with self._db.session() as s:
            row = await s.scalar(
                select(ConversationRow)
                .where(ConversationRow.id == conversation_id)
                .options(selectinload(ConversationRow.messages).selectinload(MessageRow.citations))
            )
        if row is None:
            raise not_found("conversation_not_found", CONVERSATION_NOT_FOUND)
        return row

    async def create(self, title: str | None, document_id: str | None) -> ConversationRow:
        async with self._tx.track("conversation.create") as tracked:
            async with self._db.session() as s:
                await _ensure_document(s, document_id)
                now = now_iso()
                row = ConversationRow(
                    id=new_id("conv"),
                    title=clean_title(title) if title and title.strip() else DEFAULT_TITLE,
                    document_id=document_id,
                    document_deleted=False,
                    created_at=now,
                    updated_at=now,
                )
                s.add(row)
            tracked.entity_id = row.id
            return row

    async def update(
        self,
        conversation_id: str,
        *,
        title: object = UNSET,
        document_id: object = UNSET,
    ) -> ConversationRow:
        """Only the given fields change (``str | None``, or ``UNSET`` to leave as is).
        Renaming does not reorder the sidebar."""
        action = "conversation.rename" if title is not UNSET else "conversation.update"
        async with self._tx.track(action, conversation_id):
            async with self._db.session() as s:
                row = await s.get(ConversationRow, conversation_id)
                if row is None:
                    raise not_found("conversation_not_found", CONVERSATION_NOT_FOUND)
                if title is not UNSET:
                    row.title = clean_title(title if isinstance(title, str) else "")
                if document_id is not UNSET:
                    new_doc = document_id if isinstance(document_id, str) else None
                    await _ensure_document(s, new_doc)
                    row.document_id = new_doc
                    row.document_deleted = False
            return row

    async def delete(self, conversation_id: str) -> None:
        async with (
            self._tx.track("conversation.delete", conversation_id),
            self._db.session() as s,
        ):
            row = await s.get(ConversationRow, conversation_id)
            if row is None:
                raise not_found("conversation_not_found", CONVERSATION_NOT_FOUND)
            await s.delete(row)  # messages and citations cascade in the database
