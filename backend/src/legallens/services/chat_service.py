"""Chat turns streamed over SSE (FR-6 to FR-18, FR-22).

Flow of one turn:
  1. ``start()`` validates the request and pulls the orchestrator's first event (the intent).
     Errors up to here are normal JSON errors (e.g. 503 when the model runtime is down) and
     nothing is saved.
  2. It saves the user message and an empty assistant message (``streaming``), then returns
     a ``ChatStream``.
  3. ``ChatStream`` relays events as SSE from a producer task that also persists the reply:
     ``complete`` on done, ``stopped`` when the client disconnects, ``error`` on failure.
"""

import asyncio
import json
import time
from collections.abc import AsyncIterator, Sequence
from datetime import timedelta
from typing import Any

import anyio
import structlog
from sqlalchemy import func, select, update

from legallens.api.schemas import ChatRequest, Citation
from legallens.config import Settings
from legallens.db.engine import Database
from legallens.db.models import (
    CitationRow,
    ConversationRow,
    DocumentPageRow,
    DocumentRow,
    MessageRow,
)
from legallens.errors import (
    CONVERSATION_NOT_FOUND,
    DOCUMENT_NOT_FOUND,
    AppError,
    conflict,
    not_found,
    unprocessable,
)
from legallens.ids import iso, new_id, now_iso, utc_now
from legallens.logging import current_request_id
from legallens.ports.ingestion import PageText
from legallens.ports.orchestrator import (
    ChatContext,
    ChatOrchestrator,
    CitationEvent,
    DocumentRef,
    DoneEvent,
    IntentEvent,
    ModelUnavailableError,
    OrchestratorError,
    OrchestratorEvent,
    StatusEvent,
    TokenEvent,
    Turn,
)
from legallens.services.conversation_service import DEFAULT_TITLE
from legallens.services.transaction_logger import TransactionLogger

log = structlog.get_logger("legallens.chat")

PING = b": ping\n\n"
TITLE_CHARS = 48
PARTIAL_SAVE_INTERVAL_S = 1.0
MAX_QUOTE_CHARS = 500


def encode_sse(event: str, data: dict[str, Any]) -> bytes:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n".encode()


def title_from(message: str) -> str:
    clean = " ".join(message.split()).rstrip("?.!")
    clean = clean[:1].upper() + clean[1:]
    return clean if len(clean) <= TITLE_CHARS else clean[: TITLE_CHARS - 1].rstrip() + "…"


class DbPageReader:
    """Gives the orchestrator read-only access to a document's extracted text."""

    def __init__(self, db: Database, document_id: str) -> None:
        self._db = db
        self._document_id = document_id

    @staticmethod
    def _to_page(row: DocumentPageRow) -> PageText:
        return PageText(
            page=row.page,
            paragraphs=list(row.paragraphs),
            section=row.section,
            ocr=row.ocr,
            ocr_confidence=row.ocr_confidence,
        )

    async def page(self, number: int) -> PageText | None:
        async with self._db.session() as s:
            row = await s.get(DocumentPageRow, (self._document_id, number))
        return self._to_page(row) if row else None

    async def all_pages(self) -> list[PageText]:
        async with self._db.session() as s:
            rows = await s.scalars(
                select(DocumentPageRow)
                .where(DocumentPageRow.document_id == self._document_id)
                .order_by(DocumentPageRow.page)
            )
            return [self._to_page(r) for r in rows.all()]


class ChatService:
    def __init__(
        self,
        db: Database,
        orchestrator: ChatOrchestrator,
        tx: TransactionLogger,
        settings: Settings,
    ) -> None:
        self._db = db
        self._orchestrator = orchestrator
        self._tx = tx
        self._settings = settings
        self._busy: set[str] = set()  # conversations with a reply in progress

    @property
    def settings(self) -> Settings:
        return self._settings

    def release(self, conversation_id: str) -> None:
        self._busy.discard(conversation_id)

    async def recover_interrupted(self) -> int:
        """Marks replies left ``streaming`` by a crash or restart as failed."""
        async with self._db.session() as s:
            result = await s.execute(
                update(MessageRow)
                .where(MessageRow.status == "streaming")
                .values(
                    status="error",
                    error_code="stream_interrupted",
                    error_message="This reply was interrupted because Legal Lens restarted.",
                    error_request_id="none",
                )
            )
        count: int = getattr(result, "rowcount", 0) or 0
        return count

    async def start(self, req: ChatRequest) -> "ChatStream":
        started = time.perf_counter()
        request_id = current_request_id()
        try:
            return await self._start(req, started, request_id)
        except AppError as exc:
            await self._tx.record(
                "chat.message",
                status="error",
                error_code=exc.code,
                latency_ms=(time.perf_counter() - started) * 1000,
                entity_id=req.conversation_id,
                request_id=request_id,
            )
            raise

    async def _start(self, req: ChatRequest, started: float, request_id: str) -> "ChatStream":
        text = req.message.strip()
        if not text:
            raise unprocessable("empty_message", "Message cannot be empty.")
        limit = self._settings.max_message_chars
        if len(text) > limit:
            raise unprocessable(
                "message_too_long", f"Messages are limited to {limit:,} characters."
            )
        if len(req.document_ids) > 1:
            raise unprocessable(
                "too_many_documents",
                "Select one document at a time. Multi-document questions are not supported yet.",
            )
        document_id = req.document_ids[0] if req.document_ids else None

        async with self._db.session() as s:
            conversation = await s.get(ConversationRow, req.conversation_id)
            if conversation is None:
                raise not_found("conversation_not_found", CONVERSATION_NOT_FOUND)
            document = await s.get(DocumentRow, document_id) if document_id else None
            if document_id and document is None:
                raise not_found("document_not_found", DOCUMENT_NOT_FOUND)
            if document is not None and document.status != "ready":
                raise conflict(
                    "document_not_ready",
                    "That document is not ready yet. Wait for processing to finish.",
                )
            history = await self._history(s, conversation.id)

        if conversation.id in self._busy:
            raise conflict(
                "conversation_busy",
                "A reply is still being written in this conversation. Wait for it, or stop it.",
            )
        self._busy.add(conversation.id)

        events: AsyncIterator[OrchestratorEvent] | None = None
        try:
            ctx = ChatContext(
                request_id=request_id,
                conversation_id=conversation.id,
                message=text,
                document=DocumentRef(
                    id=document.id,
                    name=document.name,
                    type="pdf" if document.type == "pdf" else "docx",
                    pages=document.pages or 0,
                )
                if document
                else None,
                history=history,
                pages=DbPageReader(self._db, document.id) if document else None,
            )
            events = self._orchestrator.stream(ctx)
            first = await self._first_event(events)
            user_id, assistant_id, title = await self._save_turn(
                conversation.id, text, document_id, first
            )
        except BaseException:
            self.release(conversation.id)
            if events is not None:
                await _aclose(events)
            raise

        log.info("chat_started", conversation_id=conversation.id, intent=first.intent)
        return ChatStream(
            service=self,
            events=events,
            intent=first,
            conversation_id=conversation.id,
            user_message_id=user_id,
            assistant_message_id=assistant_id,
            document=document,
            title=title,
            started=started,
            request_id=request_id,
        )

    async def _history(self, s: Any, conversation_id: str) -> Sequence[Turn]:
        n = self._settings.history_turns * 2
        if n == 0:
            return []
        rows = await s.scalars(
            select(MessageRow)
            .where(
                MessageRow.conversation_id == conversation_id,
                MessageRow.status.in_(("complete", "stopped")),
            )
            .order_by(MessageRow.seq.desc())
            .limit(n)
        )
        return [
            Turn(
                role="user" if r.role == "user" else "assistant", content=r.content, intent=r.intent
            )
            for r in reversed(rows.all())
        ]

    async def _first_event(self, events: AsyncIterator[OrchestratorEvent]) -> IntentEvent:
        try:
            async with asyncio.timeout(self._settings.stream_first_event_timeout_s):
                first = await anext(events)
        except ModelUnavailableError as exc:
            raise AppError(503, exc.code, exc.message) from exc
        except TimeoutError as exc:
            raise AppError(
                504, "model_timeout", "The local model took too long to respond. Try again."
            ) from exc
        except OrchestratorError as exc:
            raise AppError(502, exc.code, exc.message) from exc
        except StopAsyncIteration as exc:
            raise AppError(502, "empty_response", "The model returned no answer.") from exc
        if not isinstance(first, IntentEvent):
            raise TypeError(
                f"Orchestrator must yield IntentEvent first, got {type(first).__name__}"
            )
        return first

    async def _save_turn(
        self, conversation_id: str, text: str, document_id: str | None, intent: IntentEvent
    ) -> tuple[str, str, str]:
        async with self._db.session() as s:
            conversation = await s.get(ConversationRow, conversation_id)
            if conversation is None:
                raise not_found("conversation_not_found", CONVERSATION_NOT_FOUND)
            last_seq = await s.scalar(
                select(func.max(MessageRow.seq)).where(
                    MessageRow.conversation_id == conversation_id
                )
            )
            seq = last_seq or 0
            now = utc_now()
            user = MessageRow(
                id=new_id("msg"),
                conversation_id=conversation_id,
                seq=seq + 1,
                role="user",
                content=text,
                status="complete",
                intent=None,
                outcome=None,
                suggestions=[],
                document_id=document_id,
                created_at=iso(now),
            )
            assistant = MessageRow(
                id=new_id("msg"),
                conversation_id=conversation_id,
                seq=seq + 2,
                role="assistant",
                content="",
                status="streaming",
                intent=intent.intent,
                outcome=None,
                suggestions=[],
                document_id=document_id,
                created_at=iso(now + timedelta(milliseconds=1)),
            )
            s.add_all([user, assistant])
            conversation.updated_at = assistant.created_at
            if document_id:
                conversation.document_id = document_id
                conversation.document_deleted = False
            if conversation.title == DEFAULT_TITLE:
                conversation.title = title_from(text)
            return user.id, assistant.id, conversation.title

    # ------------------------------------------------------------ used by ChatStream

    async def save_partial(self, assistant_message_id: str, content: str) -> None:
        async with self._db.session() as s:
            await s.execute(
                update(MessageRow)
                .where(MessageRow.id == assistant_message_id, MessageRow.status == "streaming")
                .values(content=content)
            )

    async def finish(
        self,
        stream: "ChatStream",
        *,
        status: str,
        content: str,
        citations: Sequence[Citation],
        outcome: str | None = None,
        suggestions: Sequence[str] = (),
        error: AppError | None = None,
        ttft_ms: float | None = None,
    ) -> None:
        try:
            async with self._db.session() as s:
                message = await s.get(MessageRow, stream.assistant_message_id)
                if message is not None:  # None when the conversation was deleted mid-reply
                    message.content = content
                    message.status = status
                    message.outcome = outcome
                    message.suggestions = list(suggestions)
                    if error is not None:
                        message.error_code = error.code
                        message.error_message = error.message
                        message.error_request_id = stream.request_id
                    s.add_all(
                        CitationRow(
                            message_id=message.id,
                            idx=c.index,
                            document_id=c.document_id,
                            document_name=c.document_name,
                            page=c.page,
                            section=c.section,
                            quote=c.quote,
                            chunk_id=None,
                        )
                        for c in citations
                    )
                    await s.execute(
                        update(ConversationRow)
                        .where(ConversationRow.id == stream.conversation_id)
                        .values(updated_at=now_iso())
                    )
        finally:
            await self._tx.record(
                "chat.message",
                status="ok" if status == "complete" else status,
                latency_ms=(time.perf_counter() - stream.started) * 1000,
                ttft_ms=ttft_ms,
                entity_id=stream.conversation_id,
                error_code=error.code if error else None,
                request_id=stream.request_id,
            )
            log.info(
                "chat_finished",
                conversation_id=stream.conversation_id,
                status=status,
                outcome=outcome,
                citations=len(citations),
                ttft_ms=None if ttft_ms is None else round(ttft_ms),
            )


async def _aclose(events: AsyncIterator[OrchestratorEvent]) -> None:
    close = getattr(events, "aclose", None)
    if close is not None:
        try:
            await close()
        except Exception:
            log.warning("orchestrator_close_failed")


class ChatStream:
    """One assistant reply in flight. ``sse()`` yields the encoded event stream."""

    def __init__(
        self,
        *,
        service: ChatService,
        events: AsyncIterator[OrchestratorEvent],
        intent: IntentEvent,
        conversation_id: str,
        user_message_id: str,
        assistant_message_id: str,
        document: DocumentRow | None,
        title: str,
        started: float,
        request_id: str,
    ) -> None:
        self._service = service
        self._events = events
        self._intent = intent
        self.conversation_id = conversation_id
        self.user_message_id = user_message_id
        self.assistant_message_id = assistant_message_id
        self._document = document
        self._title = title
        self.started = started
        self.request_id = request_id
        self._settings = service.settings
        self._producer: asyncio.Task[None] | None = None
        self._closed = False

    async def sse(self) -> AsyncIterator[bytes]:
        queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._producer = asyncio.create_task(self._produce(queue), name="chat-producer")
        try:
            while True:
                try:
                    async with asyncio.timeout(self._settings.sse_ping_interval_s):
                        item = await queue.get()
                except TimeoutError:
                    yield PING
                    continue
                if item is None:
                    return
                yield item
        finally:
            await self.aclose()

    async def aclose(self) -> None:
        """Stops the reply if it is still running (client gone) and waits until it is saved.
        Safe to call more than once, and before ``sse()`` was ever iterated."""
        if self._closed:
            return
        self._closed = True
        with anyio.CancelScope(shield=True):
            if self._producer is None:
                # The response never started streaming: save what we have (nothing).
                try:
                    await self._safe_finish(status="stopped", content="", citations=[])
                finally:
                    self._service.release(self.conversation_id)
                    await _aclose(self._events)
                return
            if not self._producer.done():
                self._producer.cancel()
            await asyncio.wait({self._producer})

    async def _produce(self, queue: "asyncio.Queue[bytes | None]") -> None:
        content: list[str] = []
        citations: list[Citation] = []
        seen: set[int] = set()
        ttft_ms: float | None = None
        last_save = time.monotonic()
        put = queue.put_nowait
        ids = {"message_id": self.assistant_message_id, "user_message_id": self.user_message_id}
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._settings.stream_total_timeout_s
        try:
            put(encode_sse("intent", {"intent": self._intent.intent, **ids}))
            try:
                done: DoneEvent | None = None
                async with asyncio.timeout_at(deadline):
                    async for event in self._events:
                        if isinstance(event, StatusEvent):
                            put(encode_sse("status", {"label": event.label}))
                        elif isinstance(event, TokenEvent):
                            if ttft_ms is None:
                                ttft_ms = (time.perf_counter() - self.started) * 1000
                            content.append(event.text)
                            put(encode_sse("token", {"text": event.text}))
                            if time.monotonic() - last_save >= PARTIAL_SAVE_INTERVAL_S:
                                last_save = time.monotonic()
                                await self._service.save_partial(
                                    self.assistant_message_id, "".join(content)
                                )
                        elif isinstance(event, CitationEvent):
                            citation = self._accept(event, seen)
                            if citation is not None:
                                citations.append(citation)
                                put(encode_sse("citation", citation.model_dump(by_alias=True)))
                        elif isinstance(event, DoneEvent):
                            done = event
                            break
                if done is None:
                    raise OrchestratorError(
                        "incomplete_response", "The model stopped before finishing its answer."
                    )
            except asyncio.CancelledError:
                # The client disconnected or pressed Stop: keep what was generated so far.
                await self._safe_finish(
                    status="stopped",
                    content="".join(content),
                    citations=citations,
                    ttft_ms=ttft_ms,
                )
                raise
            except Exception as exc:
                error = self._to_error(exc)
                await self._safe_finish(
                    status="error",
                    content="".join(content),
                    citations=citations,
                    error=error,
                    ttft_ms=ttft_ms,
                )
                put(self._error_event(error))
                return

            saved = await self._safe_finish(
                status="complete",
                content="".join(content),
                citations=citations,
                outcome=done.outcome,
                suggestions=done.suggestions,
                ttft_ms=ttft_ms,
            )
            if not saved:
                put(
                    self._error_event(
                        AppError(500, "save_failed", "The answer could not be saved.")
                    )
                )
                return
            put(
                encode_sse(
                    "done",
                    {
                        **ids,
                        "outcome": done.outcome,
                        "suggestions": list(done.suggestions),
                        "title": self._title,
                    },
                )
            )
        finally:
            put(None)
            self._service.release(self.conversation_id)
            await _aclose(self._events)

    async def _safe_finish(self, **kwargs: Any) -> bool:
        try:
            await self._service.finish(self, **kwargs)
        except Exception:
            log.exception("chat_save_failed", conversation_id=self.conversation_id)
            return False
        return True

    def _error_event(self, error: AppError) -> bytes:
        return encode_sse(
            "error", {"code": error.code, "message": error.message, "request_id": self.request_id}
        )

    @staticmethod
    def _to_error(exc: Exception) -> AppError:
        if isinstance(exc, TimeoutError):
            return AppError(504, "model_timeout", "The answer took too long and was stopped.")
        if isinstance(exc, OrchestratorError):
            return AppError(502, exc.code, exc.message)
        log.error("chat_stream_failed", error=type(exc).__name__, exc_info=exc)
        return AppError(500, "internal_error", "Something went wrong while writing the answer.")

    def _accept(self, event: CitationEvent, seen: set[int]) -> Citation | None:
        """Backend-side citation guard. The full citation verifier is part of the AI layer."""
        doc = self._document
        reason = None
        if doc is None or event.document_id != doc.id:
            reason = "wrong_document"
        elif event.index < 1 or event.index in seen:
            reason = "bad_index"
        elif not 1 <= event.page <= (doc.pages or 0):
            reason = "page_out_of_range"
        elif not event.quote.strip():
            reason = "empty_quote"
        if reason is not None or doc is None:
            log.warning("citation_dropped", reason=reason, index=event.index)
            return None
        seen.add(event.index)
        quote = " ".join(event.quote.split())
        if len(quote) > MAX_QUOTE_CHARS:
            quote = quote[: MAX_QUOTE_CHARS - 1] + "…"
        return Citation(
            index=event.index,
            document_id=doc.id,
            document_name=doc.name,
            page=event.page,
            section=event.section,
            quote=quote,
        )
