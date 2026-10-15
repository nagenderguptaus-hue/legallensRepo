"""Data types and errors for document ingestion."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal

from legallens_ai.errors import OrchestratorError
from legallens_ai.retrieval.types import IndexedDocument
from legallens_ai.schemas import PageText

# Same stage names as the backend's ingestion port, so progress maps through unchanged.
Stage = Literal["validating", "extracting", "ocr", "quality_check", "chunking", "indexing"]
# progress(stage, current, total)
Progress = Callable[[Stage, int | None, int | None], Awaitable[None]]
Route = Literal["digital", "ocr"]


@dataclass(frozen=True)
class PageReport:
    """How one page was read: for the CLI report and the logs (never text)."""

    page: int
    route: Route
    paragraphs: int
    words: int
    ocr_confidence: float | None
    ms: float


@dataclass(frozen=True)
class IngestionOutcome:
    pages: list[PageText]
    is_scanned: bool
    warnings: list[str]
    document: IndexedDocument
    reports: list[PageReport] = field(default_factory=list)


class IngestionError(OrchestratorError):
    """Ingestion cannot succeed. ``message`` is shown on the document card; ``retryable`` tells
    the backend's job runner whether another attempt might work."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(code, message)
        self.retryable = retryable
