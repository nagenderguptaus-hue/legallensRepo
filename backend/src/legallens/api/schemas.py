"""Request/response models. They mirror ``frontend/src/api/types.ts`` field for field.

Casing follows the frontend contract: resources are camelCase; the chat request, SSE control
payloads and the error envelope are snake_case.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from legallens.db.models import CitationRow, ConversationRow, DocumentRow, MessageRow

Intent = Literal["ask", "summary", "draft", "clarify"]
Outcome = Literal["answered", "not_found", "clarify", "needs_document"]
DocumentStatus = Literal["processing", "ready", "failed"]
IngestionStage = Literal["validating", "extracting", "ocr", "quality_check", "chunking", "indexing"]
MessageStatus = Literal["complete", "streaming", "stopped", "error"]


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
    )


class ApiErrorBody(BaseModel):
    code: str
    message: str
    request_id: str


# ---------------------------------------------------------------- health


class Health(CamelModel):
    status: Literal["ok", "degraded"]
    model_runtime: Literal["ready", "loading", "unavailable"]
    model: str
    # "cloud": answers come from a hosted model (Claude), so messages and document passages
    # leave this machine. The UI words its privacy note accordingly.
    processing: Literal["local", "cloud"]


# ---------------------------------------------------------------- documents


class Progress(CamelModel):
    current: int
    total: int


class LegalDocument(CamelModel):
    id: str
    name: str
    type: Literal["pdf", "docx"]
    size_bytes: int
    pages: int | None
    status: DocumentStatus
    stage: IngestionStage | None
    progress: Progress | None
    is_scanned: bool
    warnings: list[str]
    error: str | None
    uploaded_at: str

    @classmethod
    def from_row(cls, row: DocumentRow) -> "LegalDocument":
        progress = (
            Progress(current=row.progress_current, total=row.progress_total)
            if row.progress_current is not None and row.progress_total is not None
            else None
        )
        return cls.model_validate(
            {
                "id": row.id,
                "name": row.name,
                "type": row.type,
                "size_bytes": row.size_bytes,
                "pages": row.pages,
                "status": row.status,
                "stage": row.stage,
                "progress": progress,
                "is_scanned": row.is_scanned,
                "warnings": row.warnings,
                "error": row.error,
                "uploaded_at": row.uploaded_at,
            }
        )


class DocumentPage(CamelModel):
    document_id: str
    page: int
    total_pages: int
    paragraphs: list[str]
    ocr: bool
    ocr_confidence: float | None


# ---------------------------------------------------------------- conversations


class Citation(CamelModel):
    index: int
    document_id: str
    document_name: str
    page: int
    section: str | None
    quote: str

    @classmethod
    def from_row(cls, row: CitationRow) -> "Citation":
        return cls(
            index=row.idx,
            document_id=row.document_id,
            document_name=row.document_name,
            page=row.page,
            section=row.section,
            quote=row.quote,
        )


class Message(CamelModel):
    id: str
    conversation_id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: str
    status: MessageStatus
    intent: Intent | None
    outcome: Outcome | None
    citations: list[Citation]
    suggestions: list[str]
    document_id: str | None
    # Omitted when absent: the frontend type is `error?: ApiErrorBody`.
    error: ApiErrorBody | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description="Present when status is 'error'.",
    )

    @classmethod
    def from_row(cls, row: MessageRow) -> "Message":
        error = (
            ApiErrorBody(
                code=row.error_code,
                message=row.error_message or "",
                request_id=row.error_request_id or "unknown",
            )
            if row.error_code
            else None
        )
        return cls.model_validate(
            {
                "id": row.id,
                "conversation_id": row.conversation_id,
                "role": row.role,
                "content": row.content,
                "created_at": row.created_at,
                "status": row.status,
                "intent": row.intent,
                "outcome": row.outcome,
                "citations": [Citation.from_row(c) for c in row.citations],
                "suggestions": row.suggestions,
                "document_id": row.document_id,
                "error": error,
            }
        )


class Conversation(CamelModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    document_id: str | None
    document_deleted: bool

    @classmethod
    def from_row(cls, row: ConversationRow) -> "Conversation":
        return cls(
            id=row.id,
            title=row.title,
            created_at=row.created_at,
            updated_at=row.updated_at,
            document_id=row.document_id,
            document_deleted=row.document_deleted,
        )


class ConversationDetail(Conversation):
    messages: list[Message]

    @classmethod
    def from_row_with_messages(cls, row: ConversationRow) -> "ConversationDetail":
        return cls(
            **Conversation.from_row(row).model_dump(by_alias=False),
            messages=[Message.from_row(m) for m in row.messages],
        )


class ConversationCreate(CamelModel):
    title: str | None = Field(default=None, max_length=1000)
    document_id: str | None = None


class ConversationPatch(CamelModel):
    """Fields left out are unchanged. ``documentId: null`` clears the document."""

    title: str | None = Field(default=None, max_length=1000)
    document_id: str | None = None


# ---------------------------------------------------------------- chat


class ChatRequest(BaseModel):
    conversation_id: str
    message: str
    document_ids: list[str] = []
