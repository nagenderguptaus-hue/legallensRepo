"""The AI layer behind the backend's two ports: chat (Claude) and ingestion (OCR + index).

Turn it on with ``uv sync --extra ai`` and, in ``.env``::

    LL_ORCHESTRATOR=legallens.adapters.ai:create_orchestrator
    LL_INGESTION=legallens.adapters.ai:create_ingestion
    ANTHROPIC_API_KEY=...            (or in ai/.env)

Both factories return parts of one ``AIStack`` per AI data folder: embedded Qdrant locks its
folder, so chat and ingestion must share one retrieval stack (ai/orchestration.todo.md O2).
At startup the stack loads the search models in the background (O6) and indexes Ready
documents that are not in the AI index yet, from the page text already in the database (O5).

This module only translates: ``ChatContext`` → ``OrchestratorRequest``, AI-layer events and
errors → the port's. Routing and the workflows live in ``ai/`` (``legallens_ai``).
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from pathlib import Path

import structlog
from legallens_ai import errors as ai_errors
from legallens_ai import events as ai
from legallens_ai.engine import BackfillDocument, ChatEngine
from legallens_ai.orchestrator import TurnTrace
from legallens_ai.runtime import AIRuntime
from legallens_ai.schemas import DocumentInfo, OrchestratorRequest
from legallens_ai.schemas import PageText as AIPageText
from legallens_ai.schemas import Turn as AITurn
from legallens_ai.streams import closing
from sqlalchemy import select

from legallens.adapters.ai_ingestion import AIIngestionPipeline, ai_settings_for
from legallens.config import Settings
from legallens.db.engine import Database
from legallens.db.models import DocumentRow
from legallens.ports.orchestrator import (
    ChatContext,
    CitationEvent,
    DoneEvent,
    IntentEvent,
    ModelUnavailableError,
    OrchestratorError,
    OrchestratorEvent,
    RuntimeHealth,
    StatusEvent,
    TokenEvent,
)
from legallens.services.chat_service import DbPageReader

log = structlog.get_logger("legallens.ai")

INGESTION_FACTORY = "legallens.adapters.ai:create_ingestion"
# Both build the stack's shared ingestion pipeline (ai_ingestion:create is the older name).
SHARED_INGESTION_FACTORIES = frozenset(
    {INGESTION_FACTORY, "legallens.adapters.ai_ingestion:create"}
)
# HTTP status for AI-layer errors raised before the reply starts streaming. Default 502.
ERROR_STATUS = {
    "document_not_indexed": 409,
    "document_too_large": 422,
}


# ---------------------------------------------------------------- translation


def to_request(ctx: ChatContext) -> OrchestratorRequest:
    doc = ctx.document
    return OrchestratorRequest(
        message=ctx.message,
        history=[AITurn(role=t.role, content=t.content, intent=t.intent) for t in ctx.history],
        document=DocumentInfo(id=doc.id, name=doc.name, type=doc.type, pages=doc.pages)
        if doc
        else None,
        conversation_id=ctx.conversation_id,
        request_id=ctx.request_id,
    )


def to_event(event: ai.OrchestratorEvent) -> OrchestratorEvent:
    match event:
        case ai.IntentEvent(intent=intent):
            return IntentEvent(intent)
        case ai.StatusEvent(label=label):
            return StatusEvent(label)
        case ai.TokenEvent(text=text):
            return TokenEvent(text)
        case ai.CitationEvent():
            return CitationEvent(
                index=event.index,
                document_id=event.document_id,
                page=event.page,
                quote=event.quote,
                section=event.section,
                chunk_id=event.chunk_id,
            )
        case ai.DoneEvent(outcome=outcome, suggestions=suggestions):
            return DoneEvent(outcome, tuple(suggestions))
    raise TypeError(f"Unknown AI-layer event {type(event).__name__}")


def to_error(exc: ai_errors.OrchestratorError) -> OrchestratorError:
    if isinstance(exc, ai_errors.ModelUnavailableError):
        return ModelUnavailableError(exc.message)
    return OrchestratorError(exc.code, exc.message, status=ERROR_STATUS.get(exc.code, 502))


# ---------------------------------------------------------------- the stack


class AIStack:
    """One process's AI layer for one data folder: the runtime, the chat engine, and the
    two port adapters built on them."""

    def __init__(self, settings: Settings, runtime: AIRuntime, engine: ChatEngine) -> None:
        self.settings = settings
        self.runtime = runtime
        self.engine = engine
        self.orchestrator = AIChatOrchestrator(self)
        self.ingestion = SharedAIIngestionPipeline(self)
        self._startup: asyncio.Task[None] | None = None
        self._closed = False

    def start(self) -> None:
        """Starts warm-up + backfill in the background. Needs a running event loop and the
        migrated database, so it is called from the factory (inside ``build_container``) and
        again on every health check and chat turn: a warm-up that failed (e.g. no network
        for the first model download) is retried, otherwise the UI, which blocks sending
        while the model is unavailable, could never recover."""
        if self._closed:
            return
        task = self._startup
        if task is None or (task.done() and not self.engine.warm):
            self._startup = asyncio.get_running_loop().create_task(
                self._run_startup(), name="ai-startup"
            )

    async def wait_startup(self) -> None:
        """Waits until warm-up and backfill have finished (tests, scripts)."""
        self.start()
        if self._startup is not None:
            await asyncio.shield(self._startup)

    async def _run_startup(self) -> None:
        try:
            await self.engine.warm_up()
        except Exception as exc:  # reported by health; chat retries the warm-up
            log.warning("ai_warm_up_failed", error=type(exc).__name__)
            return
        try:
            await self.backfill()
        except Exception as exc:
            log.warning("ai_backfill_failed", error=type(exc).__name__)

    async def backfill(self) -> int:
        """Indexes Ready documents missing from the AI index. Returns how many were indexed."""
        db = Database(self.settings.db_path)
        indexed = 0
        try:
            async with db.session() as s:
                rows = (
                    await s.execute(
                        select(DocumentRow.id, DocumentRow.name, DocumentRow.type)
                        .where(DocumentRow.status == "ready")
                        .order_by(DocumentRow.uploaded_at)
                    )
                ).all()
            for document_id, name, type_ in rows:
                reader = DbPageReader(db, document_id)

                async def load(reader: DbPageReader = reader) -> list[AIPageText]:
                    return [
                        AIPageText(
                            page=p.page,
                            paragraphs=p.paragraphs,
                            section=p.section,
                            ocr=p.ocr,
                            ocr_confidence=p.ocr_confidence,
                        )
                        for p in await reader.all_pages()
                    ]

                doc = BackfillDocument(
                    id=document_id, name=name, type="pdf" if type_ == "pdf" else "docx"
                )
                try:
                    if not await self.engine.backfill(doc, load):
                        continue
                except ai_errors.OrchestratorError as exc:
                    log.warning(
                        "ai_backfill_document_failed", document_id=document_id, code=exc.code
                    )
                    continue
                indexed += 1
                # Deleted while it was being indexed: don't leave orphan chunks behind.
                async with db.session() as s:
                    still_there = await s.get(DocumentRow, document_id) is not None
                if not still_there:
                    await (await self.runtime.retrieval()).indexer.purge(document_id)
        finally:
            await db.dispose()
        if indexed:
            log.info("ai_backfill_done", indexed=indexed)
        return indexed

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._startup is not None and not self._startup.done():
            self._startup.cancel()
            await asyncio.gather(self._startup, return_exceptions=True)
        await self.engine.close()
        await self.runtime.close()
        _STACKS.pop(_key(self.runtime), None)


class AIChatOrchestrator:
    """The backend's ``ChatOrchestrator`` port over ``ChatEngine``."""

    def __init__(self, stack: AIStack) -> None:
        self._stack = stack

    async def health(self) -> RuntimeHealth:
        self._stack.start()
        status = self._stack.engine.status()
        return RuntimeHealth(status=status.state, model=status.model, processing="cloud")

    async def stream(self, ctx: ChatContext) -> AsyncIterator[OrchestratorEvent]:
        self._stack.start()
        trace = TurnTrace()
        try:
            async with closing(self._stack.engine.stream(to_request(ctx), trace)) as events:
                async for event in events:
                    yield to_event(event)
        except ai_errors.OrchestratorError as exc:
            raise to_error(exc) from exc
        finally:
            # One line per turn, metadata only (NFR-5, NFR-10). The request id comes from
            # the logging context; the conversation id is logged explicitly.
            log.info("ai_turn", conversation_id=ctx.conversation_id, **trace.metadata())

    async def aclose(self) -> None:
        await self._stack.aclose()


class SharedAIIngestionPipeline(AIIngestionPipeline):
    """The ingestion adapter on the stack's shared runtime. ``Container.shutdown`` closes
    the pipeline, which closes the whole stack (chat included)."""

    def __init__(self, stack: AIStack) -> None:
        super().__init__(stack.runtime)
        self._stack = stack

    async def aclose(self) -> None:
        await self._stack.aclose()


# ---------------------------------------------------------------- factories

_STACKS: dict[Path, AIStack] = {}


def _key(runtime: AIRuntime) -> Path:
    return runtime.settings.data_dir.expanduser().resolve()


def stack_for(settings: Settings) -> AIStack:
    """The process's stack for this backend's AI data folder, created on first use."""
    ai_settings = ai_settings_for(settings)
    key = ai_settings.data_dir.expanduser().resolve()
    stack = _STACKS.get(key)
    if stack is None:
        runtime = AIRuntime(ai_settings)
        stack = _STACKS[key] = AIStack(settings, runtime, ChatEngine(runtime))
    return stack


def create_orchestrator(settings: Settings) -> AIChatOrchestrator:
    if settings.ingestion not in SHARED_INGESTION_FACTORIES:
        # O4: chat answers from the AI index, which only the AI ingestion fills (and both
        # must share one index). Fail at startup rather than on every message.
        raise ValueError(
            f"LL_ORCHESTRATOR=legallens.adapters.ai:create_orchestrator needs "
            f"LL_INGESTION={INGESTION_FACTORY} (got {settings.ingestion!r})."
        )
    stack = stack_for(settings)
    # Inside build_container the database is migrated by now. Without a running event loop
    # (a plain function call), the stack starts on first use instead.
    with contextlib.suppress(RuntimeError):
        stack.start()
    return stack.orchestrator


def create_ingestion(settings: Settings) -> SharedAIIngestionPipeline:
    return stack_for(settings).ingestion
