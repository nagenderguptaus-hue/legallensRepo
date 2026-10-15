from pathlib import Path
from typing import Any, cast

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableLambda

from legallens_ai.errors import DocumentNotIndexedError, DocumentTooLargeError
from legallens_ai.events import CitationEvent, DoneEvent, StatusEvent, TokenEvent, WorkflowEvent
from legallens_ai.query_rewriter import QueryRewrite, QueryRewriter
from legallens_ai.retrieval.chunk_store import ChunkStore
from legallens_ai.retrieval.hybrid import HybridRetriever
from legallens_ai.retrieval.indexer import DocumentIndexer
from legallens_ai.schemas import DocumentInfo, OrchestratorRequest, PageText, Turn
from legallens_ai.workflows import (
    AskTrace,
    AskWorkflow,
    DraftTrace,
    DraftWorkflow,
    SummaryTrace,
    SummaryWorkflow,
)
from legallens_ai.workflows.checks import NOT_FOUND
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


async def collect(events: Any) -> list[WorkflowEvent]:
    return [e async for e in events]


class Env:
    def __init__(self, tmp_path: Path) -> None:
        self.store = ChunkStore(tmp_path / "chunks.db")
        embedder = FakeEmbedder()
        vectors = InMemoryVectorStore()
        self.indexer = DocumentIndexer(self.store, embedder, vectors)
        self.retriever = HybridRetriever(
            self.store, embedder, vectors, FakeReranker(), vector_k=3, keyword_k=3, top_n=2
        )
        self.rewrites: list[str] = []

    async def index(self) -> None:
        await self.indexer.index(document_id=DOC.id, name=DOC.name, type="pdf", pages=PAGES)

    def rewriter(self, relation: str = "follow_up", query: str = "") -> QueryRewriter:
        async def respond(prompt: Any) -> dict[str, Any]:
            self.rewrites.append(str(prompt.to_messages()[-1].content))
            parsed = QueryRewrite(rationale="r", relation=relation, standalone_query=query)
            return {"raw": None, "parsed": parsed, "parsing_error": None}

        return QueryRewriter(RunnableLambda(respond), model_name="fake-haiku")

    def ask(self, llm: FakeStreamingLLM, *, min_score: float = -9.5, **rewrite: str) -> AskWorkflow:
        return AskWorkflow(
            rewriter=self.rewriter(**rewrite),
            store=self.store,
            retriever=self.retriever,
            llm=cast(BaseChatModel, llm),
            model_name="claude-sonnet-5-5",
            min_score=min_score,
        )


# ---------------------------------------------------------------- ask


async def test_ask_streams_status_tokens_citations_then_done(tmp_path: Path) -> None:
    env = Env(tmp_path)
    await env.index()
    llm = FakeStreamingLLM(
        [
            text_chunk(0, "", [citation("doc_lease:00002", 1, 2, "Tenant may terminate early.")]),
            text_chunk(0, "Yes, with notice."),
            final_chunk(),
        ]
    )
    trace = AskTrace()
    request = OrchestratorRequest(message="Can the tenant terminate early?", document=DOC)
    events = await collect(env.ask(llm).run(request, trace))

    assert [type(e) for e in events] == [
        StatusEvent,
        StatusEvent,
        CitationEvent,
        TokenEvent,
        TokenEvent,
        DoneEvent,
    ]
    assert [e.label for e in events if isinstance(e, StatusEvent)] == [
        "Searching Lease.pdf",
        "Writing the answer",
    ]  # no "follow-up" status without history
    assert "".join(e.text for e in events if isinstance(e, TokenEvent)) == "Yes, with notice. [1]"
    cite = next(e for e in events if isinstance(e, CitationEvent))
    assert (cite.index, cite.page, cite.document_id) == (1, 3, "doc_lease")
    assert events[-1] == DoneEvent("answered")
    assert trace.rewrite is not None and trace.rewrite.reason == "no_history"
    assert env.rewrites == []  # guardrail 1: no rewriter call
    # Sonnet received the retrieved chunks as search results, then the question.
    blocks = llm.last_blocks
    assert all(b["type"] == "search_result" for b in blocks[:-1])
    assert "<question>\nCan the tenant terminate early?\n</question>" in llm.last_text
    assert "<standalone_question>" not in llm.last_text


async def test_ask_follow_up_is_rewritten_before_retrieval(tmp_path: Path) -> None:
    env = Env(tmp_path)
    await env.index()
    llm = FakeStreamingLLM()
    history = [Turn("user", "How much is the deposit?"), Turn("assistant", "$9,000 [1].", "ask")]
    trace = AskTrace()
    request = OrchestratorRequest(message="When is it returned?", history=history, document=DOC)
    events = await collect(
        env.ask(llm, query="When is the security deposit returned?").run(request, trace)
    )
    assert isinstance(events[0], StatusEvent)
    assert events[0].label == "Understanding your follow-up question"
    assert trace.rewrite is not None and trace.rewrite.rewritten
    assert trace.retrieval is not None
    assert trace.retrieval.query == "When is the security deposit returned?"
    assert "<standalone_question>\nWhen is the security deposit returned?" in llm.last_text


async def test_ask_gate_answers_not_found_without_calling_the_model(tmp_path: Path) -> None:
    env = Env(tmp_path)
    await env.index()
    llm = FakeStreamingLLM()
    trace = AskTrace()
    request = OrchestratorRequest(message="What is the capital of France?", document=DOC)
    events = await collect(env.ask(llm, min_score=-8.5).run(request, trace))  # best is -9 ("of")
    assert llm.calls == []
    assert trace.gated
    assert TokenEvent(NOT_FOUND) in events
    assert events[-1] == DoneEvent("not_found")


async def test_ask_model_not_found_reply_sets_the_outcome(tmp_path: Path) -> None:
    env = Env(tmp_path)
    await env.index()
    llm = FakeStreamingLLM([text_chunk(0, NOT_FOUND), final_chunk()])
    trace = AskTrace()
    events = await collect(
        env.ask(llm, min_score=-99).run(
            OrchestratorRequest(message="Is there a non-compete?", document=DOC), trace
        )
    )
    assert events[-1] == DoneEvent("not_found")
    assert trace.warnings == []


async def test_ask_uncited_answer_is_flagged(tmp_path: Path) -> None:
    env = Env(tmp_path)
    await env.index()
    trace = AskTrace()
    await collect(
        env.ask(FakeStreamingLLM(), min_score=-99).run(
            OrchestratorRequest(message="Rent?", document=DOC), trace
        )
    )
    assert trace.outcome == "answered"
    assert trace.warnings == ["uncited_answer"]


async def test_ask_without_a_document_or_index(tmp_path: Path) -> None:
    env = Env(tmp_path)
    events = await collect(env.ask(FakeStreamingLLM()).run(OrchestratorRequest(message="Rent?")))
    assert events[-1] == DoneEvent("needs_document")
    with pytest.raises(DocumentNotIndexedError):
        await collect(env.ask(FakeStreamingLLM()).run(OrchestratorRequest("Rent?", document=DOC)))


# ---------------------------------------------------------------- summary


def summary_workflow(env: Env, llms: dict[str, FakeStreamingLLM], **kw: Any) -> SummaryWorkflow:
    return SummaryWorkflow(
        store=env.store,
        llm_for=lambda model: cast(BaseChatModel, llms.setdefault(model, FakeStreamingLLM())),
        short_model="claude-sonnet-5-5",
        long_model="claude-opus-5-5",
        long_threshold_tokens=kw.get("long_threshold_tokens", 60_000),
        max_document_tokens=kw.get("max_document_tokens", 400_000),
    )


async def test_summary_sends_every_chunk_and_picks_the_model_by_length(tmp_path: Path) -> None:
    env = Env(tmp_path)
    await env.index()
    llms: dict[str, FakeStreamingLLM] = {}
    trace = SummaryTrace()
    request = OrchestratorRequest(message="Summarize this", document=DOC)
    await collect(summary_workflow(env, llms).run(request, trace))
    assert trace.model == "claude-sonnet-5-5"
    blocks = llms["claude-sonnet-5-5"].last_blocks
    assert [b["source"] for b in blocks[:-1]] == [
        c.chunk_id for c in await env.store.chunks(DOC.id)
    ]
    assert "cache_control" in blocks[-2]  # the document is prompt-cached
    # the stub answer has none of the six sections
    assert len([w for w in trace.warnings if w.startswith("missing_section:")]) == 6

    long = summary_workflow(env, {}, long_threshold_tokens=10)
    trace = SummaryTrace()
    await collect(long.run(request, trace))
    assert trace.model == "claude-opus-5-5"


async def test_summary_refuses_documents_over_the_budget(tmp_path: Path) -> None:
    env = Env(tmp_path)
    await env.index()
    with pytest.raises(DocumentTooLargeError):
        await collect(
            summary_workflow(env, {}, max_document_tokens=5).run(
                OrchestratorRequest(message="Summarize", document=DOC)
            )
        )


# ---------------------------------------------------------------- draft


def draft_workflow(env: Env, llm: FakeStreamingLLM) -> DraftWorkflow:
    return DraftWorkflow(
        store=env.store,
        llm=cast(BaseChatModel, llm),
        model_name="claude-opus-5-5",
        max_document_tokens=400_000,
        history_turns=2,
        turn_chars=50,
    )


async def test_draft_without_a_document_uses_instructions_only(tmp_path: Path) -> None:
    env = Env(tmp_path)
    llm = FakeStreamingLLM(
        [text_chunk(0, "MEMORANDUM [CONFIRM: client name] per Smith v. Jones."), final_chunk()]
    )
    trace = DraftTrace()
    events = await collect(
        draft_workflow(env, llm).run(OrchestratorRequest(message="Draft a memo on X"), trace)
    )
    assert events[-1] == DoneEvent("answered")
    assert [b["type"] for b in llm.last_blocks] == ["text"]
    assert "No reference document was provided" in llm.last_text
    assert trace.check is not None
    assert trace.check.placeholders == 1
    assert trace.check.invented_citations == ("Smith v. Jones",)
    assert trace.warnings == ["invented_citation"]


async def test_draft_revision_sends_the_previous_draft_in_full(tmp_path: Path) -> None:
    env = Env(tmp_path)
    await env.index()
    llm = FakeStreamingLLM()
    long_draft = "MEMORANDUM " + "analysis " * 100 + "END-OF-DRAFT"
    history = [
        Turn("user", "Draft a memo on early termination"),
        Turn("assistant", long_draft, "draft"),
        Turn("user", "Also, what is the rent?"),
        Turn("assistant", "Rent is $4,500 per month " + "x" * 200, "ask"),
    ]
    trace = DraftTrace()
    request = OrchestratorRequest(message="Make it shorter", history=history, document=DOC)
    events = await collect(draft_workflow(env, llm).run(request, trace))
    assert trace.revising and trace.reference_chunks == 3
    assert StatusEvent("Revising the draft") in events
    assert "END-OF-DRAFT" in llm.last_text  # older than the 2-turn window, kept whole
    assert "…[truncated]" in llm.last_text  # other turns are still clipped
    assert [b["type"] for b in llm.last_blocks[:-1]] == ["search_result"] * 3
