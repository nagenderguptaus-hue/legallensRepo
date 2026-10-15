"""The AI layer as one chat service, for an app that embeds this package (the backend).

``ChatEngine`` sits on the process's shared ``AIRuntime`` (one retrieval stack: embedded
Qdrant locks its folder) and adds what an always-on app needs around ``Orchestrator.stream()``
(orchestration.todo.md):

  - ``warm_up()``: loads the embedding and reranker models in the background at startup, so
    the first question doesn't wait for a multi-GB download (O6);
  - ``status()``: ``unavailable`` / ``loading`` / ``ready`` for the health check, with no API
    call (health is polled);
  - ``backfill()``: indexes a document from page text the app already stored, for documents
    ingested before the AI index existed (O5);
  - ``stream()``: one chat turn.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from legallens_ai.config import AISettings
from legallens_ai.errors import DocumentNotIndexedError, OrchestratorError
from legallens_ai.events import OrchestratorEvent
from legallens_ai.intent_classifier import IntentClassifier
from legallens_ai.orchestrator import Orchestrator, TurnTrace, Workflows
from legallens_ai.retrieval import Retrieval
from legallens_ai.runtime import AIRuntime
from legallens_ai.schemas import OrchestratorRequest, PageText
from legallens_ai.streams import closing
from legallens_ai.workflows import AskWorkflow, DraftWorkflow, SummaryWorkflow

log = logging.getLogger("legallens_ai.engine")

EngineState = Literal["loading", "ready", "unavailable"]
BEING_PREPARED = "This document is still being prepared for AI search. Try again in a minute."
_WARM_UP_TEXT = "warm up"


def model_name(model_id: str) -> str:
    """``claude-sonnet-5-5`` → ``Sonnet 5.5``. Unknown shapes are returned unchanged."""
    parts = model_id.removeprefix("claude-").split("-")
    family, version = parts[0], [p for p in parts[1:] if p.isdigit() and len(p) <= 2]
    if not family.isalpha() or not version:
        return model_id
    return f"{family.capitalize()} {'.'.join(version)}"


def model_label(settings: AISettings) -> str:
    """The models chat uses, generation first: e.g. ``Claude Sonnet 5.5 · Opus 5.5 · Haiku 4.5``."""
    ids = (
        settings.ask_model,
        settings.summary_model,
        settings.summary_long_model,
        settings.draft_model,
        settings.intent_model,
        settings.rewrite_model,
    )
    names = list(dict.fromkeys(model_name(i) for i in ids))
    return "Claude " + " · ".join(names)


def build_workflows(settings: AISettings, retrieval: Retrieval) -> Workflows:
    return Workflows(
        ask=AskWorkflow.from_settings(
            settings, store=retrieval.store, retriever=retrieval.retriever
        ),
        summary=SummaryWorkflow.from_settings(settings, store=retrieval.store),
        draft=DraftWorkflow.from_settings(settings, store=retrieval.store),
    )


@dataclass(frozen=True)
class EngineStatus:
    state: EngineState
    model: str
    reason: str | None = None  # why it is unavailable


@dataclass(frozen=True)
class BackfillDocument:
    id: str
    name: str
    type: Literal["pdf", "docx"]


class _RuntimeWorkflows:
    """The orchestrator's ``WorkflowSource``: workflows on the runtime's retrieval stack."""

    def __init__(self, engine: "ChatEngine") -> None:
        self._engine = engine
        self._built_for: Retrieval | None = None
        self._workflows: Workflows | None = None

    @property
    def ready(self) -> bool:
        return self._engine.warm

    async def get(self) -> Workflows:
        retrieval = await self._engine.warm_up()
        if self._workflows is None or self._built_for is not retrieval:
            self._workflows = self._engine.make_workflows(retrieval)
            self._built_for = retrieval
        return self._workflows


class ChatEngine:
    def __init__(
        self,
        runtime: AIRuntime,
        *,
        classifier: IntentClassifier | None = None,
        workflows: Callable[[Retrieval], Workflows] | None = None,
    ) -> None:
        """``classifier`` / ``workflows`` replace the Claude-backed ones (tests)."""
        self.runtime = runtime
        self.settings = runtime.settings
        self._classifier = classifier
        self._make_workflows = workflows or (lambda r: build_workflows(self.settings, r))
        self._source = _RuntimeWorkflows(self)
        self._orchestrator: Orchestrator | None = None
        self._warm_task: asyncio.Task[Retrieval] | None = None
        self._warm_error: str | None = None
        self.warm = False
        self._backfilling: set[str] = set()

    def make_workflows(self, retrieval: Retrieval) -> Workflows:
        return self._make_workflows(retrieval)

    # ------------------------------------------------------------ health

    def status(self) -> EngineStatus:
        label = model_label(self.settings)
        if self._classifier is None:
            key = self.settings.anthropic_api_key
            if key is None or not key.get_secret_value():
                return EngineStatus(
                    "unavailable", label, "ANTHROPIC_API_KEY is not set for the AI layer."
                )
        if self._warm_error is not None and not self.warm:
            return EngineStatus("unavailable", label, self._warm_error)
        return EngineStatus("ready" if self.warm else "loading", label)

    async def warm_up(self) -> Retrieval:
        """Opens the retrieval stack and loads its models once. Concurrent callers share the
        same load; after a failure the next call tries again."""
        task = self._warm_task
        if task is None or (task.done() and (task.cancelled() or task.exception() is not None)):
            task = self._warm_task = asyncio.create_task(self._warm(), name="ai-warm-up")
        return await asyncio.shield(task)

    async def _warm(self) -> Retrieval:
        try:
            retrieval = await self.runtime.retrieval()
            await retrieval.embedder.embed_query(_WARM_UP_TEXT)
            await retrieval.reranker.scores(_WARM_UP_TEXT, [_WARM_UP_TEXT])
        except OrchestratorError as exc:
            self._warm_error = exc.message
            log.warning("warm_up_failed code=%s", exc.code)
            raise
        except Exception as exc:
            self._warm_error = "The search models could not be loaded. Check the logs."
            log.warning("warm_up_failed error=%s", type(exc).__name__)
            raise
        self._warm_error = None
        self.warm = True
        log.info("warm_up_done")
        return retrieval

    # ------------------------------------------------------------ backfill

    def is_backfilling(self, document_id: str) -> bool:
        return document_id in self._backfilling

    async def backfill(
        self,
        document: BackfillDocument,
        load_pages: Callable[[], Awaitable[Sequence[PageText]]],
    ) -> bool:
        """Indexes ``document`` from stored page text unless it is already in the index.
        Returns True if it was indexed now."""
        retrieval = await self.runtime.retrieval()
        if await retrieval.store.document(document.id) is not None:
            return False
        self._backfilling.add(document.id)
        try:
            pages = await load_pages()
            if not any(p.paragraphs for p in pages):
                log.info("backfill_skipped document_id=%s reason=no_text", document.id)
                return False
            await retrieval.indexer.index(
                document_id=document.id, name=document.name, type=document.type, pages=pages
            )
        finally:
            self._backfilling.discard(document.id)
        log.info("backfill_indexed document_id=%s pages=%d", document.id, len(pages))
        return True

    # ------------------------------------------------------------ chat

    def orchestrator(self) -> Orchestrator:
        """Built on first use: a missing API key surfaces as a chat error, not a crash."""
        if self._orchestrator is None:
            classifier = self._classifier or IntentClassifier.from_settings(self.settings)
            self._orchestrator = Orchestrator(classifier, self._source)
        return self._orchestrator

    async def stream(
        self, request: OrchestratorRequest, trace: TurnTrace | None = None
    ) -> AsyncIterator[OrchestratorEvent]:
        if request.document is not None and self.is_backfilling(request.document.id):
            raise DocumentNotIndexedError(BEING_PREPARED)
        async with closing(self.orchestrator().stream(request, trace)) as events:
            async for event in events:
                yield event

    async def close(self) -> None:
        """Stops a warm-up still in progress. The runtime is closed by its owner."""
        task = self._warm_task
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
