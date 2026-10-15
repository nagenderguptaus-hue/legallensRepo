"""Orchestrator.stream() and ChatEngine: routing → workflow dispatch, offline (fake models)."""

import asyncio
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any, cast

import anthropic
import httpx2
import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.runnables import RunnableLambda

from legallens_ai.config import AISettings
from legallens_ai.engine import (
    BEING_PREPARED,
    BackfillDocument,
    ChatEngine,
    model_label,
    model_name,
)
from legallens_ai.errors import DocumentNotIndexedError, ModelUnavailableError
from legallens_ai.events import (
    CitationEvent,
    DoneEvent,
    IntentEvent,
    OrchestratorEvent,
    StatusEvent,
    TokenEvent,
)
from legallens_ai.intent_classifier import IntentClassifier
from legallens_ai.orchestrator import (
    LOADING_MODELS,
    NEEDS_DOCUMENT,
    Orchestrator,
    TurnTrace,
    Workflows,
)
from legallens_ai.query_rewriter import QueryRewrite, QueryRewriter
from legallens_ai.retrieval import Retrieval
from legallens_ai.retrieval.chunk_store import ChunkStore
from legallens_ai.retrieval.hybrid import HybridRetriever
from legallens_ai.retrieval.indexer import DocumentIndexer
from legallens_ai.runtime import AIRuntime
from legallens_ai.schemas import DocumentInfo, Intent, OrchestratorRequest, PageText, Turn
from legallens_ai.workflows import AskWorkflow, DraftWorkflow, SummaryWorkflow
from legallens_ai.workflows.clarify import NO_DOCUMENT_SUGGESTIONS, WITH_DOCUMENT_SUGGESTIONS
from tests.fakes import FakeStructuredLLM
from tests.workflow_fakes import (
    FakeEmbedder,
    FakeReranker,
    FakeStreamingLLM,
    InMemoryVectorStore,
    citation,
    final_chunk,
    text_chunk,
)

DOC = DocumentInfo(id="doc_lease", name="Lease.pdf", type="pdf", pages=3)
PAGES = [
    PageText(1, ["1. Rent", "Tenant shall pay monthly Base Rent of $4,500."], "1. Rent"),
    PageText(2, ["2. Deposit", "Tenant shall deposit $9,000 as security."], "2. Deposit"),
    PageText(3, ["3. Termination", "Tenant may terminate early with notice."], "3. Termination"),
]
SECRET = "Can the tenant terminate early?"  # must never appear in trace metadata
REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


class ClosableLLM(FakeStreamingLLM):
    """Records whether its stream was closed (the HTTP stream, in the real client)."""

    def __init__(self, chunks: list[AIMessageChunk] | None = None) -> None:
        super().__init__(chunks)
        self.closed = False

    async def astream(self, messages: list[BaseMessage], **_: Any) -> AsyncIterator[AIMessageChunk]:
        self.calls.append(messages)
        try:
            for chunk in self.chunks:
                yield chunk
        finally:
            self.closed = True


def answer_llm() -> ClosableLLM:
    return ClosableLLM(
        [
            text_chunk(0, "", [citation("doc_lease:00002", 1, 2, "Tenant may terminate early.")]),
            text_chunk(0, "Yes, with notice."),
            text_chunk(0, " More text."),
            final_chunk(),
        ]
    )


def make_retrieval(tmp_path: Path) -> Retrieval:
    store = ChunkStore(tmp_path / "chunks.db")
    embedder = FakeEmbedder()
    vectors = InMemoryVectorStore()
    reranker = FakeReranker()
    return Retrieval(
        store=store,
        embedder=embedder,
        reranker=reranker,
        vectors=vectors,
        indexer=DocumentIndexer(store, embedder, vectors),
        retriever=HybridRetriever(
            store, embedder, vectors, reranker, vector_k=3, keyword_k=3, top_n=2
        ),
    )


def rewriter() -> QueryRewriter:
    async def respond(_: Any) -> dict[str, Any]:
        parsed = QueryRewrite(rationale="r", relation="standalone", standalone_query="")
        return {"raw": None, "parsed": parsed, "parsing_error": None}

    return QueryRewriter(RunnableLambda(respond), model_name="fake-haiku")


def workflows_on(retrieval: Retrieval, llm: FakeStreamingLLM) -> Workflows:
    chat = cast(BaseChatModel, llm)
    return Workflows(
        ask=AskWorkflow(
            rewriter=rewriter(),
            store=retrieval.store,
            retriever=retrieval.retriever,
            llm=chat,
            model_name="claude-sonnet-5-5",
            min_score=-9.5,
        ),
        summary=SummaryWorkflow(
            store=retrieval.store,
            llm_for=lambda _: chat,
            short_model="claude-sonnet-5-5",
            long_model="claude-opus-5-5",
            long_threshold_tokens=60_000,
            max_document_tokens=400_000,
        ),
        draft=DraftWorkflow(
            store=retrieval.store,
            llm=chat,
            model_name="claude-opus-5-5",
            max_document_tokens=400_000,
        ),
    )


def classifier(intent: Intent = "ask", **kwargs: Any) -> IntentClassifier:
    fake = FakeStructuredLLM(intent, "The lawyer wants X.", **kwargs)
    return IntentClassifier(fake.runnable(), model_name="fake-haiku")


async def index(retrieval: Retrieval) -> None:
    await retrieval.indexer.index(document_id=DOC.id, name=DOC.name, type="pdf", pages=PAGES)


async def collect(events: AsyncIterator[OrchestratorEvent]) -> list[OrchestratorEvent]:
    return [e async for e in events]


def text_of(events: Sequence[OrchestratorEvent]) -> str:
    return "".join(e.text for e in events if isinstance(e, TokenEvent))


def done_of(events: Sequence[OrchestratorEvent]) -> DoneEvent:
    done = events[-1]
    assert isinstance(done, DoneEvent)
    return done


# ---------------------------------------------------------------- Orchestrator.stream()


async def test_ask_turn_streams_intent_first_then_the_cited_answer(tmp_path: Path) -> None:
    retrieval = make_retrieval(tmp_path)
    await index(retrieval)
    llm = answer_llm()
    orch = Orchestrator(classifier("ask"), workflows_on(retrieval, llm))
    trace = TurnTrace()

    events = await collect(orch.stream(OrchestratorRequest(message=SECRET, document=DOC), trace))

    assert events[0] == IntentEvent("ask")
    assert [type(e) for e in events[1:3]] == [StatusEvent, StatusEvent]
    assert any(isinstance(e, CitationEvent) and e.page == 3 for e in events)
    assert text_of(events) == "Yes, with notice. More text. [1]"
    assert done_of(events).outcome == "answered"
    assert trace.status == "ok" and trace.ask is not None and trace.ask.outcome == "answered"
    assert trace.first_token_ms is not None and trace.total_ms >= trace.first_token_ms


@pytest.mark.parametrize("intent", ["summary", "draft"])
async def test_summary_and_draft_turns_run_their_workflow(tmp_path: Path, intent: Intent) -> None:
    retrieval = make_retrieval(tmp_path)
    await index(retrieval)
    llm = FakeStreamingLLM([text_chunk(0, "The output."), final_chunk()])
    trace = TurnTrace()
    events = await collect(
        Orchestrator(classifier(intent), workflows_on(retrieval, llm)).stream(
            OrchestratorRequest(message="Do it", document=DOC), trace
        )
    )
    assert events[0] == IntentEvent(intent)
    assert text_of(events) == "The output."
    assert done_of(events).outcome == "answered"
    assert (trace.summary if intent == "summary" else trace.draft) is not None
    assert len(llm.calls) == 1


async def test_draft_without_a_document_still_runs(tmp_path: Path) -> None:
    llm = FakeStreamingLLM([text_chunk(0, "MEMORANDUM"), final_chunk()])
    events = await collect(
        Orchestrator(classifier("draft"), workflows_on(make_retrieval(tmp_path), llm)).stream(
            OrchestratorRequest(message="Draft a demand letter")
        )
    )
    assert text_of(events) == "MEMORANDUM"
    assert done_of(events).outcome == "answered"


@pytest.mark.parametrize("intent", ["ask", "summary"])
async def test_missing_document_gets_a_fixed_reply_without_any_workflow(
    tmp_path: Path, intent: Intent
) -> None:
    llm = FakeStreamingLLM()
    events = await collect(
        Orchestrator(classifier(intent), workflows_on(make_retrieval(tmp_path), llm)).stream(
            OrchestratorRequest(message="What does it say?")
        )
    )
    assert events == [
        IntentEvent(intent),
        TokenEvent(NEEDS_DOCUMENT[intent]),
        DoneEvent("needs_document"),
    ]
    assert llm.calls == []


@pytest.mark.parametrize(
    ("document", "suggestions"),
    [(DOC, WITH_DOCUMENT_SUGGESTIONS), (None, NO_DOCUMENT_SUGGESTIONS)],
)
async def test_clarify_offers_suggestions_without_a_model_call(
    document: DocumentInfo | None, suggestions: tuple[str, ...]
) -> None:
    # No workflows at all: clarify must not need them (or the retrieval stack).
    events = await collect(
        Orchestrator(classifier("clarify")).stream(
            OrchestratorRequest(message="hmm", document=document)
        )
    )
    assert events[0] == IntentEvent("clarify")
    done = done_of(events)
    assert (done.outcome, tuple(done.suggestions)) == ("clarify", suggestions)
    assert ("Lease.pdf" in text_of(events)) is (document is not None)


async def test_routing_failure_raises_before_any_event() -> None:
    orch = Orchestrator(classifier(error=anthropic.APIConnectionError(request=REQUEST)))
    trace = TurnTrace()
    events: list[OrchestratorEvent] = []
    with pytest.raises(ModelUnavailableError):
        async for event in orch.stream(OrchestratorRequest(message="hi"), trace):
            events.append(event)
    assert events == []
    assert (trace.status, trace.error_code) == ("error", "model_unavailable")


async def test_workflow_failure_raises_after_the_intent(tmp_path: Path) -> None:
    orch = Orchestrator(classifier("ask"), workflows_on(make_retrieval(tmp_path), answer_llm()))
    events: list[OrchestratorEvent] = []
    with pytest.raises(DocumentNotIndexedError):  # nothing was indexed
        async for event in orch.stream(OrchestratorRequest(message=SECRET, document=DOC)):
            events.append(event)
    assert events == [IntentEvent("ask")]


async def test_closing_the_stream_mid_answer_closes_the_model_stream(tmp_path: Path) -> None:
    """O10: when the user presses Stop, no more tokens are generated."""
    retrieval = make_retrieval(tmp_path)
    await index(retrieval)
    llm = answer_llm()
    trace = TurnTrace()
    stream = Orchestrator(classifier("ask"), workflows_on(retrieval, llm)).stream(
        OrchestratorRequest(message=SECRET, document=DOC), trace
    )
    async for event in stream:
        if isinstance(event, TokenEvent):
            break
    await stream.aclose()  # type: ignore[attr-defined]
    assert llm.closed
    assert trace.status == "cancelled"


async def test_closing_right_after_done_still_counts_as_ok(tmp_path: Path) -> None:
    """The backend stops reading at the DoneEvent and closes the stream (found in the live
    run: every finished turn was logged as cancelled)."""
    retrieval = make_retrieval(tmp_path)
    await index(retrieval)
    trace = TurnTrace()
    stream = Orchestrator(classifier("ask"), workflows_on(retrieval, answer_llm())).stream(
        OrchestratorRequest(message=SECRET, document=DOC), trace
    )
    async for event in stream:
        if isinstance(event, DoneEvent):
            break
    await stream.aclose()  # type: ignore[attr-defined]
    assert trace.status == "ok"


async def test_trace_metadata_has_numbers_but_no_text(tmp_path: Path) -> None:
    retrieval = make_retrieval(tmp_path)
    await index(retrieval)
    trace = TurnTrace()
    await collect(
        Orchestrator(classifier("ask"), workflows_on(retrieval, answer_llm())).stream(
            OrchestratorRequest(
                message=SECRET, document=DOC, history=[Turn("user", "Earlier question")]
            ),
            trace,
        )
    )
    meta = trace.metadata()
    assert meta["intent"] == "ask" and meta["status"] == "ok"
    assert meta["citations"] == 1 and meta["gated"] is False
    assert meta["input_tokens"] == 1200 + 1000  # router + Sonnet (fake usage)
    timing_keys = [str(k) for k in meta if str(k).startswith("retrieval_")]
    assert timing_keys and all(k.endswith("_ms") and "_ms_" not in k for k in timing_keys)
    flat = repr(meta)
    for text in (SECRET, "The lawyer wants X.", "Earlier question", "terminate", "Yes, with"):
        assert text not in flat


# ---------------------------------------------------------------- ChatEngine


def engine_for(
    tmp_path: Path, retrieval: Retrieval, llm: FakeStreamingLLM, intent: Intent = "ask"
) -> ChatEngine:
    settings = AISettings(_env_file=None, data_dir=tmp_path, anthropic_api_key=None)
    return ChatEngine(
        AIRuntime(settings, retrieval=retrieval),
        classifier=classifier(intent),
        workflows=lambda r: workflows_on(r, llm),
    )


async def test_first_question_shows_model_loading_then_engine_is_ready(tmp_path: Path) -> None:
    retrieval = make_retrieval(tmp_path)
    await index(retrieval)
    engine = engine_for(tmp_path, retrieval, answer_llm())
    assert engine.status().state == "loading"

    events = await collect(engine.stream(OrchestratorRequest(message=SECRET, document=DOC)))
    assert StatusEvent(LOADING_MODELS) in events
    assert engine.status().state == "ready"

    again = await collect(engine.stream(OrchestratorRequest(message=SECRET, document=DOC)))
    assert StatusEvent(LOADING_MODELS) not in again


async def test_warm_up_loads_the_reranker_once_for_concurrent_callers(tmp_path: Path) -> None:
    retrieval = make_retrieval(tmp_path)
    engine = engine_for(tmp_path, retrieval, answer_llm())
    first, second = await asyncio.gather(engine.warm_up(), engine.warm_up())
    assert first is second is retrieval
    assert isinstance(retrieval.reranker, FakeReranker)
    assert len(retrieval.reranker.calls) == 1


async def test_failed_warm_up_reports_unavailable_and_is_retried(tmp_path: Path) -> None:
    retrieval = make_retrieval(tmp_path)
    retrieval.embedder = FakeEmbedder(fail=True)
    engine = engine_for(tmp_path, retrieval, answer_llm())
    with pytest.raises(RuntimeError):
        await engine.warm_up()
    status = engine.status()
    assert status.state == "unavailable" and status.reason

    retrieval.embedder = FakeEmbedder()
    await engine.warm_up()
    assert engine.status().state == "ready"


def test_missing_api_key_is_unavailable_without_any_call(tmp_path: Path) -> None:
    settings = AISettings(_env_file=None, data_dir=tmp_path, anthropic_api_key=None)
    status = ChatEngine(AIRuntime(settings)).status()
    assert status.state == "unavailable"
    assert status.reason is not None and "ANTHROPIC_API_KEY" in status.reason


async def test_backfill_indexes_once_and_blocks_chat_while_running(tmp_path: Path) -> None:
    retrieval = make_retrieval(tmp_path)
    engine = engine_for(tmp_path, retrieval, answer_llm())
    started, release = asyncio.Event(), asyncio.Event()

    async def load_pages() -> list[PageText]:
        started.set()
        await release.wait()
        return PAGES

    doc = BackfillDocument(id=DOC.id, name=DOC.name, type="pdf")
    task = asyncio.create_task(engine.backfill(doc, load_pages))
    await started.wait()
    assert engine.is_backfilling(DOC.id)
    with pytest.raises(DocumentNotIndexedError, match=BEING_PREPARED):
        await collect(engine.stream(OrchestratorRequest(message=SECRET, document=DOC)))

    release.set()
    assert await task is True
    assert [c.page for c in await retrieval.store.chunks(DOC.id)] == [1, 2, 3]
    assert await engine.backfill(doc, load_pages) is False  # already indexed
    events = await collect(engine.stream(OrchestratorRequest(message=SECRET, document=DOC)))
    assert done_of(events).outcome == "answered"


async def test_backfill_skips_documents_without_text(tmp_path: Path) -> None:
    retrieval = make_retrieval(tmp_path)
    engine = engine_for(tmp_path, retrieval, answer_llm())

    async def no_text() -> list[PageText]:
        return [PageText(1, [])]

    doc = BackfillDocument(id="doc_blank", name="Blank.pdf", type="pdf")
    assert await engine.backfill(doc, no_text) is False
    assert await retrieval.store.document("doc_blank") is None


def test_model_label_names_each_model_once() -> None:
    assert model_name("claude-sonnet-5-5") == "Sonnet 5.5"
    assert model_name("claude-haiku-4-5") == "Haiku 4.5"
    assert model_name("claude-haiku-4-5-20251001") == "Haiku 4.5"
    assert model_name("my-local-model") == "my-local-model"
    settings = AISettings(_env_file=None)
    assert model_label(settings) == "Claude Sonnet 5.5 · Opus 5.5 · Haiku 4.5"
