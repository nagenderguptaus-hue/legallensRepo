"""SQLite schema (``data/legallens.db``).

Timestamps are stored as fixed-width ISO 8601 UTC strings (see ``legallens.ids.iso``), which
sort correctly as text and round-trip to the API unchanged.
"""

from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, Integer, MetaData, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map: dict[Any, Any] = {  # noqa: RUF012 - SQLAlchemy class config
        list[str]: JSON,
    }


# ---------------------------------------------------------------- documents


class DocumentRow(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str]
    type: Mapped[str]
    size_bytes: Mapped[int]
    sha256: Mapped[str] = mapped_column(unique=True)
    pages: Mapped[int | None]
    is_scanned: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str]
    stage: Mapped[str | None]
    progress_current: Mapped[int | None]
    progress_total: Mapped[int | None]
    warnings: Mapped[list[str]] = mapped_column(default=list)
    error: Mapped[str | None]
    uploaded_at: Mapped[str]
    updated_at: Mapped[str]


class DocumentPageRow(Base):
    __tablename__ = "document_pages"

    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    page: Mapped[int] = mapped_column(primary_key=True)
    section: Mapped[str | None]
    paragraphs: Mapped[list[str]] = mapped_column(default=list)
    ocr: Mapped[bool] = mapped_column(default=False)
    ocr_confidence: Mapped[float | None]


class IngestionJobRow(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (Index("ix_ingestion_jobs_document_id", "document_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    state: Mapped[str]
    attempts: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None]
    created_at: Mapped[str]
    started_at: Mapped[str | None]
    finished_at: Mapped[str | None]


class ChunkRow(Base):
    """Filled by the AI layer (Phase 3). The backend only creates and deletes rows."""

    __tablename__ = "chunks"
    __table_args__ = (Index("ix_chunks_document_id", "document_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    parent_id: Mapped[str | None]
    ordinal: Mapped[int]
    page: Mapped[int]
    section: Mapped[str | None]
    heading_path: Mapped[str | None]
    text: Mapped[str]


# ---------------------------------------------------------------- conversations


class ConversationRow(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str]
    # Plain id, no foreign key: the conversation must survive its document's deletion (FR-21).
    document_id: Mapped[str | None]
    document_deleted: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[str]
    updated_at: Mapped[str]

    messages: Mapped[list["MessageRow"]] = relationship(
        back_populates="conversation",
        order_by="MessageRow.seq",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class MessageRow(Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("conversation_id", "seq"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    seq: Mapped[int]
    role: Mapped[str]
    content: Mapped[str] = mapped_column(default="")
    status: Mapped[str]
    intent: Mapped[str | None]
    outcome: Mapped[str | None]
    suggestions: Mapped[list[str]] = mapped_column(default=list)
    document_id: Mapped[str | None]
    error_code: Mapped[str | None]
    error_message: Mapped[str | None]
    error_request_id: Mapped[str | None]
    created_at: Mapped[str]

    conversation: Mapped[ConversationRow] = relationship(back_populates="messages")
    citations: Mapped[list["CitationRow"]] = relationship(
        order_by="CitationRow.idx",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )


class CitationRow(Base):
    __tablename__ = "citations"
    __table_args__ = (Index("ix_citations_message_id", "message_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"))
    idx: Mapped[int]
    document_id: Mapped[str]
    # Snapshot, so citations stay readable after the document is deleted.
    document_name: Mapped[str]
    page: Mapped[int]
    section: Mapped[str | None]
    quote: Mapped[str]
    chunk_id: Mapped[str | None]


# ---------------------------------------------------------------- audit


class TransactionRow(Base):
    __tablename__ = "transactions"
    __table_args__ = (Index("ix_transactions_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str]
    action: Mapped[str]
    entity_id: Mapped[str | None]
    status: Mapped[str]
    error_code: Mapped[str | None]
    latency_ms: Mapped[int]
    ttft_ms: Mapped[int | None]
    created_at: Mapped[str]
