"""The chat orchestration port.

The backend hands the orchestrator a ``ChatContext`` and relays the events it yields as SSE.
The orchestrator never touches HTTP and never writes to the database: ``ChatService`` assigns
message ids, persists the turn and encodes the stream.

Event protocol (enforced by ``ChatService``):
  1. exactly one ``IntentEvent`` first;
  2. any number of ``StatusEvent`` / ``TokenEvent`` / ``CitationEvent``;
  3. exactly one ``DoneEvent`` last.
Failures are raised as exceptions, never yielded.
"""

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

from legallens.ports.ingestion import PageText

Intent = Literal["ask", "summary", "draft", "clarify"]
Outcome = Literal["answered", "not_found", "clarify", "needs_document"]
RuntimeStatus = Literal["ready", "loading", "unavailable"]


@dataclass(frozen=True)
class DocumentRef:
    id: str
    name: str
    type: Literal["pdf", "docx"]
    pages: int


@dataclass(frozen=True)
class Turn:
    role: Literal["user", "assistant"]
    content: str
    intent: Intent | None = None


class PageReader(Protocol):
    """Read-only access to the selected document's extracted text."""

    async def page(self, number: int) -> PageText | None: ...

    async def all_pages(self) -> list[PageText]: ...


@dataclass(frozen=True)
class ChatContext:
    request_id: str
    conversation_id: str
    message: str
    document: DocumentRef | None
    history: Sequence[Turn]
    pages: PageReader | None


# ---------------------------------------------------------------- events


@dataclass(frozen=True)
class IntentEvent:
    intent: Intent


@dataclass(frozen=True)
class StatusEvent:
    label: str


@dataclass(frozen=True)
class TokenEvent:
    text: str


@dataclass(frozen=True)
class CitationEvent:
    index: int
    document_id: str
    page: int
    quote: str
    section: str | None = None
    chunk_id: str | None = None


@dataclass(frozen=True)
class DoneEvent:
    outcome: Outcome
    suggestions: Sequence[str] = field(default_factory=tuple)


OrchestratorEvent = IntentEvent | StatusEvent | TokenEvent | CitationEvent | DoneEvent


@dataclass(frozen=True)
class RuntimeHealth:
    status: RuntimeStatus
    model: str


# ---------------------------------------------------------------- errors


class OrchestratorError(Exception):
    """A failure the user should see, with a stable code (e.g. ``stream_interrupted``)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ModelUnavailableError(OrchestratorError):
    def __init__(
        self,
        message: str = "The local model runtime is not responding. Start it and try again.",
    ) -> None:
        super().__init__("model_unavailable", message)


class ChatOrchestrator(Protocol):
    def stream(self, ctx: ChatContext) -> AsyncIterator[OrchestratorEvent]: ...

    async def health(self) -> RuntimeHealth: ...
