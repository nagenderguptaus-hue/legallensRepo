"""The orchestrator: decides which workflow handles a chat message, then runs it.

    message + history + selected document
      → route(): Haiku classifies the intent; a plain rule flags a missing document (D8)
      → stream(): IntentEvent first, then
           needs_document        → a fixed "select a document" reply (no workflow runs)
           clarify               → ClarifyWorkflow (template + suggestions, no model call)
           ask / summary / draft → that workflow's events, streamed

``route()`` alone is what the intent eval and ``legallens-ai classify`` use. ``stream()`` is
what the backend calls for every chat turn (orchestration.todo.md O1).
"""

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal, Protocol

from legallens_ai.config import AISettings
from legallens_ai.errors import OrchestratorError
from legallens_ai.events import (
    DoneEvent,
    IntentEvent,
    OrchestratorEvent,
    StatusEvent,
    TokenEvent,
    WorkflowEvent,
)
from legallens_ai.intent_classifier import IntentClassifier
from legallens_ai.schemas import DOCUMENT_INTENTS, Intent, OrchestratorRequest, RoutingDecision
from legallens_ai.streams import closing
from legallens_ai.workflows import (
    AskTrace,
    AskWorkflow,
    DraftTrace,
    DraftWorkflow,
    SummaryTrace,
    SummaryWorkflow,
)
from legallens_ai.workflows.clarify import ClarifyWorkflow
from legallens_ai.workflows.generation import GenerationTrace

# Same wording as the backend's stand-in, which the frontend was designed around.
NEEDS_DOCUMENT: dict[Intent, str] = {
    "ask": "I answer questions **only from your documents**, so I need one to work with. "
    "Upload a PDF or Word file, or pick a Ready document from the library, then ask again.",
    "summary": "Select or upload a document and I will summarize it section by section, "
    "with citations.",
}
LOADING_MODELS = "Loading the search models (first use only)"


@dataclass(frozen=True)
class Workflows:
    ask: AskWorkflow
    summary: SummaryWorkflow
    draft: DraftWorkflow


class WorkflowSource(Protocol):
    """Builds the workflows on first use (they need the retrieval stack, which loads models)."""

    @property
    def ready(self) -> bool:
        """False while ``get()`` would still have to load models (shown as a status)."""
        ...

    async def get(self) -> Workflows: ...


class _Fixed:
    def __init__(self, workflows: Workflows) -> None:
        self._workflows = workflows

    @property
    def ready(self) -> bool:
        return True

    async def get(self) -> Workflows:
        return self._workflows


TurnStatus = Literal["ok", "error", "cancelled"]


def _generation(prefix: str, g: GenerationTrace | None) -> dict[str, object]:
    if g is None:
        return {}
    return {
        f"{prefix}_model": g.model or g.requested_model,
        f"{prefix}_first_token_ms": None if g.first_token_ms is None else round(g.first_token_ms),
        f"{prefix}_ms": round(g.latency_ms),
        f"{prefix}_input_tokens": g.usage.input_tokens,
        f"{prefix}_output_tokens": g.usage.output_tokens,
        f"{prefix}_cache_read_tokens": g.cache_read_tokens,
        f"{prefix}_stop_reason": g.stop_reason,
        "citations": len(g.citations),
    }


@dataclass
class TurnTrace:
    """What happened in one chat turn. ``metadata()`` is safe to log (NFR-5): ids, models,
    counts, scores and timings only, never message, rationale or document text."""

    routing: RoutingDecision | None = None
    ask: AskTrace | None = None
    summary: SummaryTrace | None = None
    draft: DraftTrace | None = None
    status: TurnStatus | None = None
    error_code: str | None = None
    first_token_ms: float | None = None
    total_ms: float = 0.0
    started: float = field(default_factory=time.perf_counter)

    @property
    def warnings(self) -> list[str]:
        workflow = self.ask or self.summary or self.draft
        return list(workflow.warnings) if workflow else []

    def metadata(self) -> dict[str, object]:
        data: dict[str, object] = {
            "status": self.status,
            "error_code": self.error_code,
            "total_ms": round(self.total_ms),
            "first_token_ms": None if self.first_token_ms is None else round(self.first_token_ms),
        }
        input_tokens = output_tokens = 0
        if r := self.routing:
            data |= {
                "intent": r.intent,
                "needs_document": r.needs_document,
                "route_model": r.model,
                "route_ms": round(r.latency_ms),
            }
            input_tokens += r.usage.input_tokens
            output_tokens += r.usage.output_tokens
        if a := self.ask:
            if a.rewrite is not None:
                data |= {
                    "rewritten": a.rewrite.rewritten,
                    "rewrite_ms": round(a.rewrite.latency_ms),
                }
                input_tokens += a.rewrite.usage.input_tokens
                output_tokens += a.rewrite.usage.output_tokens
            if a.retrieval is not None:
                best = a.retrieval.best_score
                data |= {
                    "candidates": a.retrieval.candidates,
                    "chunks_sent": 0 if a.gated else len(a.retrieval.chunks),
                    "best_score": None if best is None else round(best, 3),
                    "gated": a.gated,
                    **{
                        f"retrieval_{k.removesuffix('_ms')}_ms": round(v)
                        for k, v in a.retrieval.timings_ms.items()
                    },
                }
            data |= _generation("generation", a.generation)
            data["outcome"] = a.outcome
        if s := self.summary:
            data |= {"estimated_tokens": s.estimated_tokens, "outcome": s.outcome}
            data |= _generation("generation", s.generation)
        if d := self.draft:
            data |= {
                "reference_chunks": d.reference_chunks,
                "revising": d.revising,
                "outcome": d.outcome,
            }
            data |= _generation("generation", d.generation)
        for w in (self.ask, self.summary, self.draft):
            if w is not None and w.generation is not None:
                input_tokens += w.generation.usage.input_tokens
                output_tokens += w.generation.usage.output_tokens
        data |= {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "warnings": self.warnings,
        }
        return data


class Orchestrator:
    def __init__(
        self,
        classifier: IntentClassifier,
        workflows: Workflows | WorkflowSource | None = None,
        *,
        clarify: ClarifyWorkflow | None = None,
    ) -> None:
        """``workflows`` may be omitted for routing only (evals, ``classify``)."""
        self._classifier = classifier
        self._workflows: WorkflowSource | None = (
            _Fixed(workflows) if isinstance(workflows, Workflows) else workflows
        )
        self._clarify = clarify or ClarifyWorkflow()

    @classmethod
    def from_settings(cls, settings: AISettings | None = None) -> "Orchestrator":
        """A routing-only orchestrator. The full one is built by ``ChatEngine``."""
        return cls(IntentClassifier.from_settings(settings))

    async def route(self, request: OrchestratorRequest) -> RoutingDecision:
        result = await self._classifier.classify(request.message, request.history)
        return RoutingDecision(
            intent=result.intent,
            needs_document=result.intent in DOCUMENT_INTENTS and request.document is None,
            rationale=result.rationale,
            model=result.model,
            latency_ms=result.latency_ms,
            usage=result.usage,
        )

    async def stream(
        self, request: OrchestratorRequest, trace: TurnTrace | None = None
    ) -> AsyncIterator[OrchestratorEvent]:
        """One chat turn: ``IntentEvent``, then the chosen workflow's events.

        Errors before the ``IntentEvent`` (routing) mean nothing was answered; errors after it
        happen mid-reply. Either way they are raised, never yielded.
        """
        trace = trace if trace is not None else TurnTrace()
        trace.started = time.perf_counter()
        try:
            trace.routing = decision = await self.route(request)
            yield IntentEvent(decision.intent)
            async with closing(self._dispatch(decision, request, trace)) as events:
                async for event in events:
                    if isinstance(event, TokenEvent) and trace.first_token_ms is None:
                        trace.first_token_ms = (time.perf_counter() - trace.started) * 1000
                    if isinstance(event, DoneEvent):
                        # The reply is complete. Consumers (the backend) may close the stream
                        # right after this event, so the turn counts as ok from here.
                        trace.status = "ok"
                    yield event
        except OrchestratorError as exc:
            trace.status, trace.error_code = "error", exc.code
            raise
        except Exception:
            trace.status, trace.error_code = "error", "internal_error"
            raise
        except BaseException:  # GeneratorExit / CancelledError: the user pressed Stop
            if trace.status != "ok":
                trace.status = "cancelled"
            raise
        finally:
            trace.total_ms = (time.perf_counter() - trace.started) * 1000

    async def _dispatch(
        self, decision: RoutingDecision, request: OrchestratorRequest, trace: TurnTrace
    ) -> AsyncIterator[WorkflowEvent]:
        intent = decision.intent
        if decision.needs_document:
            yield TokenEvent(NEEDS_DOCUMENT[intent])
            yield DoneEvent("needs_document")
            return
        if intent == "clarify":
            async with closing(self._clarify.run(request)) as clarify:
                async for event in clarify:
                    yield event
            return

        if self._workflows is None:
            raise OrchestratorError(
                "workflows_not_configured", "This orchestrator was built for routing only."
            )
        if not self._workflows.ready:
            yield StatusEvent(LOADING_MODELS)
        flows = await self._workflows.get()
        events: AsyncIterator[WorkflowEvent]
        if intent == "ask":
            trace.ask = AskTrace()
            events = flows.ask.run(request, trace.ask)
        elif intent == "summary":
            trace.summary = SummaryTrace()
            events = flows.summary.run(request, trace.summary)
        else:
            trace.draft = DraftTrace()
            events = flows.draft.run(request, trace.draft)
        async with closing(events) as stream:
            async for event in stream:
                yield event
