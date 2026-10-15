"""What the orchestrator and the workflows stream back. Mirrors the backend's
``ports/orchestrator.py`` events, so the backend can relay them as SSE unchanged.

Protocol for a workflow: any number of ``StatusEvent`` / ``TokenEvent`` / ``CitationEvent``,
then exactly one ``DoneEvent``. ``Orchestrator.stream()`` puts one ``IntentEvent`` (the
router's decision) in front. Failures are raised, never yielded.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from legallens_ai.schemas import Intent, Outcome


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
    """``index`` is the ``[n]`` used inline in the text."""

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


WorkflowEvent = StatusEvent | TokenEvent | CitationEvent | DoneEvent
OrchestratorEvent = IntentEvent | WorkflowEvent
