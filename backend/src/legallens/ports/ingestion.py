"""The document ingestion port.

The backend's job runner calls ``IngestionPipeline.run`` for each uploaded document, stores
the page text it returns, and marks the document Ready or Failed. The pipeline reports live
progress through ``ProgressReporter`` (the UI polls it).
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

IngestionStage = Literal["validating", "extracting", "ocr", "quality_check", "chunking", "indexing"]


@dataclass(frozen=True)
class IngestionInput:
    document_id: str
    name: str
    type: Literal["pdf", "docx"]
    path: Path
    pages: int | None


@dataclass(frozen=True)
class PageText:
    page: int
    paragraphs: list[str]
    section: str | None = None
    ocr: bool = False
    ocr_confidence: float | None = None


@dataclass(frozen=True)
class IngestionResult:
    pages: list[PageText]
    is_scanned: bool = False
    warnings: list[str] = field(default_factory=list)


class ProgressReporter(Protocol):
    async def __call__(
        self, stage: IngestionStage, current: int | None = None, total: int | None = None
    ) -> None: ...


class IngestionFailed(Exception):
    """Ingestion cannot succeed. ``user_message`` is shown on the document card."""

    def __init__(self, user_message: str, *, retryable: bool = False) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.retryable = retryable


class IngestionPipeline(Protocol):
    async def run(self, item: IngestionInput, progress: ProgressReporter) -> IngestionResult: ...

    async def purge(self, document_id: str) -> None:
        """Delete everything the pipeline stored for this document (chunks, vectors)."""
        ...
