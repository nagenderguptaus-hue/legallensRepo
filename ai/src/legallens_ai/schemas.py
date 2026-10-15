"""Data types for the orchestrator.

``Turn`` and ``DocumentInfo`` mirror the backend's ``ports/orchestrator.py`` so the backend's
``ChatContext`` maps onto ``OrchestratorRequest`` field by field when the layers are joined.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Intent = Literal["ask", "summary", "draft", "clarify"]
Outcome = Literal["answered", "not_found", "clarify", "needs_document"]
INTENTS: tuple[Intent, ...] = ("ask", "summary", "draft", "clarify")
# Intents whose workflow reads a selected document (FR-22). Draft works without one (FR-15).
DOCUMENT_INTENTS: frozenset[Intent] = frozenset({"ask", "summary"})


@dataclass(frozen=True)
class Turn:
    role: Literal["user", "assistant"]
    content: str
    intent: Intent | None = None


@dataclass(frozen=True)
class DocumentInfo:
    id: str
    name: str
    type: Literal["pdf", "docx"]
    pages: int


@dataclass(frozen=True)
class PageText:
    """One page of extracted text: the shape the backend's ingestion port stores."""

    page: int
    paragraphs: Sequence[str]
    section: str | None = None
    ocr: bool = False
    # Character-weighted mean of the OCR engine's line scores (0 to 1); None for digital pages.
    ocr_confidence: float | None = None


@dataclass(frozen=True)
class OrchestratorRequest:
    message: str
    history: Sequence[Turn] = ()
    document: DocumentInfo | None = None
    conversation_id: str | None = None
    request_id: str | None = None


# The model's output schema. The docstring and field descriptions are sent to Claude as part of
# the JSON schema, so they are written for the model. Field order matters: the rationale is
# generated before the label.
class IntentClassification(BaseModel):
    """How to route the lawyer's latest message."""

    model_config = ConfigDict(extra="forbid")

    rationale: str = Field(
        description="One short sentence: what the lawyer wants and the rule that decides it."
    )
    intent: Intent = Field(description="The workflow that should handle the latest message.")


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class ClassifierResult:
    intent: Intent
    rationale: str
    model: str
    latency_ms: float
    usage: TokenUsage = field(default_factory=TokenUsage)


@dataclass(frozen=True)
class RoutingDecision:
    """The orchestrator's answer: which workflow runs, and whether it is missing a document."""

    intent: Intent
    needs_document: bool
    rationale: str
    model: str
    latency_ms: float
    usage: TokenUsage = field(default_factory=TokenUsage)
