"""AI chat end to end through the API (``uv sync --extra ai``), with fake models.

Real: the backend, the AI ingestion adapter, chunking, SQLite FTS5, embedded Qdrant, the
orchestrator and the Ask / Summary / Draft / Clarify workflows. Fake: the Claude models (a
scripted router and a streaming model that cites the first passage it is given) and the
embedding / reranking models, so nothing is downloaded and no API is called.
"""

import asyncio
import hashlib
import math
import re
from collections.abc import AsyncIterator, Callable, Sequence
from pathlib import Path
from typing import Any, cast

import pytest

pytest.importorskip("legallens_ai", reason="needs the AI layer: uv sync --extra ai")

import anthropic
import httpx2
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.runnables import RunnableLambda
from legallens_ai.config import AISettings
from legallens_ai.engine import ChatEngine
from legallens_ai.intent_classifier import IntentClassifier
from legallens_ai.orchestrator import Workflows
from legallens_ai.query_rewriter import QueryRewrite, QueryRewriter
from legallens_ai.retrieval import Retrieval
from legallens_ai.retrieval.chunk_store import ChunkStore
from legallens_ai.retrieval.hybrid import HybridRetriever
from legallens_ai.retrieval.indexer import DocumentIndexer
from legallens_ai.retrieval.vector_store import QdrantVectorStore
from legallens_ai.runtime import AIRuntime
from legallens_ai.schemas import Intent, IntentClassification
from legallens_ai.workflows import AskWorkflow, DraftWorkflow, SummaryWorkflow
from legallens_ai.workflows.clarify import WITH_DOCUMENT_SUGGESTIONS
from sqlalchemy import select

from legallens.adapters import load_ingestion_pipeline, load_orchestrator
from legallens.adapters.ai import (
    INGESTION_FACTORY,
    AIChatOrchestrator,
    AIStack,
    SharedAIIngestionPipeline,
    stack_for,
)
from legallens.config import Settings
from legallens.db.models import CitationRow
from tests.conftest import RunApp, parse_sse
from tests.integration.test_chat import stream_until_disconnect

REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
_WORD = re.compile(r"[a-z0-9]+")


def words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


class HashEmbedder:
    model_name = "hash"

    async def dimension(self) -> int:
        return 32

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * 32
        for word in words(text):
            vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % 32] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    async def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


class OverlapReranker:
    """Score = shared words, so the passage that matches the question ranks first."""

    model_name = "overlap"

    async def scores(self, query: str, texts: Sequence[str]) -> list[float]:
        return [float(len(words(query) & words(t))) for t in texts]


class CitingLLM:
    """A streaming Claude stand-in: cites the first passage it was sent, then answers.
    ``endless`` keeps streaming until it is closed (to test Stop); ``fail_after`` raises a
    connection error after that many text chunks."""

    def __init__(self, *, endless: bool = False, fail_after: int | None = None) -> None:
        self.endless = endless
        self.fail_after = fail_after
        self.calls = 0
        self.closed = False

    async def astream(self, messages: list[BaseMessage], **_: Any) -> AsyncIterator[AIMessageChunk]:
        self.calls += 1
        blocks = messages[-1].content
        assert isinstance(blocks, list)
        sources = [b["source"] for b in blocks if isinstance(b, dict) and b.get("source")]
        try:
            if sources:
                cite = {
                    "type": "search_result_location",
                    "source": sources[0],
                    "title": "t",
                    "cited_text": "x",
                    "search_result_index": 0,
                    "start_block_index": 0,
                    "end_block_index": 1,
                }
                yield AIMessageChunk(
                    content=[{"type": "text", "text": "", "index": 0, "citations": [cite]}]
                )
            n = 0
            while True:
                n += 1
                if self.fail_after is not None and n > self.fail_after:
                    raise anthropic.APIConnectionError(request=REQUEST)
                yield AIMessageChunk(content=[{"type": "text", "text": f"word{n} ", "index": 0}])
                if not self.endless and n == 3:
                    break
                await asyncio.sleep(0)
            yield AIMessageChunk(
                content=[],
                response_metadata={"stop_reason": "end_turn", "model_name": "claude-sonnet-5-5"},
                usage_metadata={"input_tokens": 900, "output_tokens": 30, "total_tokens": 930},
            )
        finally:
            self.closed = True


def router(pick: Callable[[str], Intent]) -> IntentClassifier:
    async def respond(prompt: Any) -> dict[str, Any]:
        latest = str(prompt.to_messages()[-1].content).rsplit("<message>", 1)[-1]
        if "ROUTER_DOWN" in latest:
            raise anthropic.APIConnectionError(request=REQUEST)
        raw = AIMessage(content="{}", response_metadata={"stop_reason": "end_turn"})
        parsed = IntentClassification(rationale="r", intent=pick(latest))
        return {"raw": raw, "parsed": parsed, "parsing_error": None}

    return IntentClassifier(RunnableLambda(respond), model_name="fake-haiku")


def keyword_intent(message: str) -> Intent:
    m = message.lower()
    if "summar" in m:
        return "summary"
    if "draft" in m:
        return "draft"
    if "hmm" in m:
        return "clarify"
    return "ask"


def standalone_rewriter() -> QueryRewriter:
    async def respond(_: Any) -> dict[str, Any]:
        parsed = QueryRewrite(rationale="r", relation="standalone", standalone_query="")
        return {"raw": None, "parsed": parsed, "parsing_error": None}

    return QueryRewriter(RunnableLambda(respond), model_name="fake-haiku")


def fake_workflows(retrieval: Retrieval, llm: CitingLLM) -> Workflows:
    chat = cast(BaseChatModel, llm)
    return Workflows(
        ask=AskWorkflow(
            rewriter=standalone_rewriter(),
            store=retrieval.store,
            retriever=retrieval.retriever,
            llm=chat,
            model_name="claude-sonnet-5-5",
            min_score=1.0,  # at least one shared word, or "not found" without the model
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


def make_stack(
    data_dir: Path,
    llm: CitingLLM,
    *,
    pick: Callable[[str], Intent] = keyword_intent,
    api_key: str | None = "test-key",
    fake_router: bool = True,
) -> AIStack:
    ai_dir = data_dir / "ai"
    store = ChunkStore(ai_dir / "chunks.db")
    embedder = HashEmbedder()
    vectors = QdrantVectorStore(collection="test", dimension=32, path=ai_dir / "qdrant")
    reranker = OverlapReranker()
    retrieval = Retrieval(
        store=store,
        embedder=embedder,
        reranker=reranker,
        vectors=vectors,
        indexer=DocumentIndexer(store, embedder, vectors),
        retriever=HybridRetriever(
            store, embedder, vectors, reranker, vector_k=5, keyword_k=5, top_n=2
        ),
    )
    ai_settings = AISettings(_env_file=None, data_dir=ai_dir, anthropic_api_key=api_key)
    runtime = AIRuntime(ai_settings, retrieval=retrieval)
    engine = ChatEngine(
        runtime,
        classifier=router(pick) if fake_router else None,
        workflows=lambda r: fake_workflows(r, llm),
    )
    settings = Settings(
        _env_file=None,
        data_dir=data_dir,
        orchestrator="legallens.adapters.ai:create_orchestrator",
        ingestion=INGESTION_FACTORY,
    )
    return AIStack(settings, runtime, engine)


def events_of(body: str) -> list[tuple[str, dict[str, Any]]]:
    return parse_sse(body)


def tokens(events: list[tuple[str, dict[str, Any]]]) -> str:
    return "".join(data["text"] for name, data in events if name == "token")


# ---------------------------------------------------------------- full turns


async def test_ask_turn_streams_a_cited_answer_and_saves_it(
    run_app: RunApp, data_dir: Path
) -> None:
    llm = CitingLLM()
    stack = make_stack(data_dir, llm)
    async with run_app(orchestrator=stack.orchestrator, pipeline=stack.ingestion) as r:
        doc = await r.ready_document()
        conversation = await r.new_conversation()
        res = await r.chat(
            conversation["id"], "How long is the term of the agreement?", [doc["id"]]
        )
        assert res.status_code == 200
        events = events_of(res.text)

        assert events[0][0] == "intent" and events[0][1]["intent"] == "ask"
        assert [d["label"] for n, d in events if n == "status"][-1] == "Writing the answer"
        assert tokens(events) == "word1 word2 word3 [1]"
        citation = next(d for n, d in events if n == "citation")
        assert citation["documentId"] == doc["id"] and citation["page"] == 2
        assert events[-1][0] == "done" and events[-1][1]["outcome"] == "answered"

        saved = (await r.client.get(f"/api/conversations/{conversation['id']}")).json()
        assistant = saved["messages"][1]
        assert assistant["status"] == "complete"
        assert assistant["content"] == "word1 word2 word3 [1]"
        assert assistant["citations"][0]["page"] == 2
        async with r.container.db.session() as s:
            row = (await s.scalars(select(CitationRow))).one()
        assert row.chunk_id is not None and row.chunk_id.startswith(doc["id"])


async def test_question_with_no_match_is_not_found_without_the_model(
    run_app: RunApp, data_dir: Path
) -> None:
    llm = CitingLLM()
    stack = make_stack(data_dir, llm)
    async with run_app(orchestrator=stack.orchestrator, pipeline=stack.ingestion) as r:
        doc = await r.ready_document()
        conversation = await r.new_conversation()
        res = await r.chat(conversation["id"], "zebra quantum?", [doc["id"]])
        events = events_of(res.text)
        assert events[-1][1]["outcome"] == "not_found"
        assert llm.calls == 0


@pytest.mark.parametrize("message", ["Summarize this document", "Draft a memo on termination"])
async def test_summary_and_draft_turns(run_app: RunApp, data_dir: Path, message: str) -> None:
    llm = CitingLLM()
    stack = make_stack(data_dir, llm)
    async with run_app(orchestrator=stack.orchestrator, pipeline=stack.ingestion) as r:
        doc = await r.ready_document()
        conversation = await r.new_conversation()
        events = events_of((await r.chat(conversation["id"], message, [doc["id"]])).text)
        assert events[0][1]["intent"] == ("summary" if "Summ" in message else "draft")
        assert any(n == "citation" for n, _ in events)
        assert events[-1][1]["outcome"] == "answered"


async def test_needs_document_and_clarify_replies(run_app: RunApp, data_dir: Path) -> None:
    llm = CitingLLM()
    stack = make_stack(data_dir, llm)
    async with run_app(orchestrator=stack.orchestrator, pipeline=stack.ingestion) as r:
        doc = await r.ready_document()
        conversation = await r.new_conversation()

        no_doc = events_of((await r.chat(conversation["id"], "What is the term?")).text)
        assert no_doc[0][1]["intent"] == "ask"
        assert no_doc[-1][1]["outcome"] == "needs_document"

        unclear = events_of((await r.chat(conversation["id"], "hmm", [doc["id"]])).text)
        assert unclear[-1][1]["outcome"] == "clarify"
        assert tuple(unclear[-1][1]["suggestions"]) == WITH_DOCUMENT_SUGGESTIONS
        assert llm.calls == 0


async def test_router_failure_is_a_503_and_nothing_is_saved(
    run_app: RunApp, data_dir: Path
) -> None:
    stack = make_stack(data_dir, CitingLLM())
    async with run_app(orchestrator=stack.orchestrator, pipeline=stack.ingestion) as r:
        conversation = await r.new_conversation()
        res = await r.chat(conversation["id"], "ROUTER_DOWN please")
        assert (res.status_code, res.json()["code"]) == (503, "model_unavailable")
        saved = (await r.client.get(f"/api/conversations/{conversation['id']}")).json()
        assert saved["messages"] == []


async def test_model_failure_mid_answer_is_an_error_event_and_saved(
    run_app: RunApp, data_dir: Path
) -> None:
    stack = make_stack(data_dir, CitingLLM(fail_after=2))
    async with run_app(orchestrator=stack.orchestrator, pipeline=stack.ingestion) as r:
        doc = await r.ready_document()
        conversation = await r.new_conversation()
        res = await r.chat(conversation["id"], "How long is the term?", [doc["id"]])
        events = events_of(res.text)
        assert events[-1][0] == "error" and events[-1][1]["code"] == "model_unavailable"
        saved = (await r.client.get(f"/api/conversations/{conversation['id']}")).json()
        assert saved["messages"][1]["status"] == "error"
        assert saved["messages"][1]["content"].startswith("word1 word2")


async def test_stop_closes_the_model_stream(run_app: RunApp, data_dir: Path) -> None:
    llm = CitingLLM(endless=True)
    stack = make_stack(data_dir, llm)
    async with run_app(orchestrator=stack.orchestrator, pipeline=stack.ingestion) as r:
        doc = await r.ready_document()
        conversation = await r.new_conversation()
        body = {
            "conversation_id": conversation["id"],
            "message": "How long is the term?",
            "document_ids": [doc["id"]],
        }
        await stream_until_disconnect(r.app, body, b"word3")
        assert llm.closed
        saved = (await r.client.get(f"/api/conversations/{conversation['id']}")).json()
        assert saved["messages"][1]["status"] == "stopped"


# ---------------------------------------------------------------- health, startup, wiring


async def test_health_reports_loading_then_ready_and_cloud_processing(
    run_app: RunApp, data_dir: Path
) -> None:
    stack = make_stack(data_dir, CitingLLM())
    async with run_app(orchestrator=stack.orchestrator, pipeline=stack.ingestion) as r:
        first = (await r.client.get("/api/health")).json()
        assert first["modelRuntime"] in ("loading", "ready")
        assert first["processing"] == "cloud"
        await stack.wait_startup()
        ready = (await r.client.get("/api/health")).json()
        assert ready["modelRuntime"] == "ready"
        assert ready["model"] == "Claude Sonnet 5.5 · Opus 5.5 · Haiku 4.5"


class BrokenEmbedder(HashEmbedder):
    async def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("model download failed")


async def test_failed_warm_up_is_retried_by_the_next_health_check(
    run_app: RunApp, data_dir: Path
) -> None:
    stack = make_stack(data_dir, CitingLLM())
    retrieval = await stack.runtime.retrieval()
    working = retrieval.embedder
    retrieval.embedder = BrokenEmbedder()
    async with run_app(orchestrator=stack.orchestrator, pipeline=stack.ingestion) as r:
        await stack.wait_startup()
        assert (await r.client.get("/api/health")).json()["modelRuntime"] == "unavailable"

        retrieval.embedder = working  # e.g. the network is back
        await r.client.get("/api/health")  # retries the warm-up in the background
        await stack.wait_startup()
        assert (await r.client.get("/api/health")).json()["modelRuntime"] == "ready"


async def test_missing_api_key_reports_unavailable(run_app: RunApp, data_dir: Path) -> None:
    stack = make_stack(data_dir, CitingLLM(), api_key=None, fake_router=False)
    async with run_app(orchestrator=stack.orchestrator, pipeline=stack.ingestion) as r:
        health = (await r.client.get("/api/health")).json()
        assert health["modelRuntime"] == "unavailable"
        conversation = await r.new_conversation()
        res = await r.chat(conversation["id"], "hello")
        assert res.json()["code"] == "model_auth_missing"


async def test_documents_ingested_before_ai_was_on_are_backfilled(
    run_app: RunApp, data_dir: Path
) -> None:
    async with run_app() as r:  # stand-in ingestion: page text only, no AI index
        doc = await r.ready_document()

    llm = CitingLLM()
    stack = make_stack(data_dir, llm)
    async with run_app(orchestrator=stack.orchestrator, pipeline=stack.ingestion) as r:
        await stack.wait_startup()
        chunks = await (await stack.runtime.retrieval()).store.chunks(doc["id"])
        assert {c.page for c in chunks} == {1, 2, 3}
        conversation = await r.new_conversation()
        res = await r.chat(conversation["id"], "How long is the term?", [doc["id"]])
        assert events_of(res.text)[-1][1]["outcome"] == "answered"


async def test_a_document_being_backfilled_is_a_409(run_app: RunApp, data_dir: Path) -> None:
    async with run_app() as r:
        doc = await r.ready_document()

    stack = make_stack(data_dir, CitingLLM())
    async with run_app(orchestrator=stack.orchestrator, pipeline=stack.ingestion) as r:
        await stack.wait_startup()
        await (await stack.runtime.retrieval()).indexer.purge(doc["id"])
        release = asyncio.Event()

        async def slow_pages() -> list[Any]:
            await release.wait()
            return []

        from legallens_ai.engine import BackfillDocument

        task = asyncio.create_task(
            stack.engine.backfill(BackfillDocument(doc["id"], doc["name"], "pdf"), slow_pages)
        )
        await asyncio.sleep(0.05)
        conversation = await r.new_conversation()
        res = await r.chat(conversation["id"], "How long is the term?", [doc["id"]])
        assert (res.status_code, res.json()["code"]) == (409, "document_not_indexed")
        release.set()
        await task


def test_factories_share_one_stack_and_require_ai_ingestion(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        orchestrator="legallens.adapters.ai:create_orchestrator",
        ingestion=INGESTION_FACTORY,
    )
    orchestrator = load_orchestrator(settings)
    pipeline = load_ingestion_pipeline(settings)
    assert isinstance(orchestrator, AIChatOrchestrator)
    assert isinstance(pipeline, SharedAIIngestionPipeline)
    assert stack_for(settings).orchestrator is orchestrator
    assert stack_for(settings).ingestion is pipeline

    # The older ingestion setting builds the same shared pipeline.
    older = settings.model_copy(update={"ingestion": "legallens.adapters.ai_ingestion:create"})
    assert load_ingestion_pipeline(older) is pipeline
    assert load_orchestrator(older) is orchestrator

    standin = settings.model_copy(update={"ingestion": "standin"})
    with pytest.raises(ValueError, match=re.escape(f"LL_INGESTION={INGESTION_FACTORY}")):
        load_orchestrator(standin)
