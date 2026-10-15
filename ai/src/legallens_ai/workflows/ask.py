"""The Ask workflow: a question about one document, answered only from it, with citations.

    question + history
      → pre-retrieval: QueryRewriter (Haiku 4.5; skipped when there is no history)
      → retrieval: HybridRetriever (vector 25 + BM25 25 → union → reranker → top 8)
      → sufficiency gate: best rerank score below threshold → "not found", no LLM call (W18)
      → generation: Sonnet 5.5 over the 8 chunks as cited search results, streamed
      → outcome: not_found if the model gave the fixed "not found" reply, else answered

Yields ``StatusEvent`` / ``TokenEvent`` / ``CitationEvent`` and one final ``DoneEvent``.
Pass an ``AskTrace`` to ``run()`` to see what happened at each step (CLI, evals).
"""

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from langchain_core.language_models import BaseChatModel

from legallens_ai.config import AISettings
from legallens_ai.errors import DocumentNotIndexedError
from legallens_ai.events import DoneEvent, StatusEvent, TokenEvent, WorkflowEvent
from legallens_ai.llm import generation_model
from legallens_ai.prompting import escape, load_prompt
from legallens_ai.query_rewriter import QueryRewriter, RewriteResult
from legallens_ai.retrieval.chunk_store import ChunkStore
from legallens_ai.retrieval.hybrid import HybridRetriever
from legallens_ai.retrieval.types import RetrievalResult
from legallens_ai.schemas import OrchestratorRequest, Outcome
from legallens_ai.streams import closing
from legallens_ai.workflows.checks import NOT_FOUND, is_not_found
from legallens_ai.workflows.generation import (
    GenerationTrace,
    build_messages,
    stream_with_citations,
)

log = logging.getLogger("legallens_ai.ask")

NEEDS_DOCUMENT = "Select a Ready document to ask about, or upload one first."


@dataclass
class AskTrace:
    rewrite: RewriteResult | None = None
    retrieval: RetrievalResult | None = None
    gated: bool = False  # True: the sufficiency gate answered "not found" without the LLM
    generation: GenerationTrace | None = None
    outcome: Outcome | None = None
    warnings: list[str] = field(default_factory=list)


def render_question(rewrite: RewriteResult) -> str:
    lines = ["<question>", escape(rewrite.original), "</question>"]
    if rewrite.rewritten:
        lines += ["<standalone_question>", escape(rewrite.query), "</standalone_question>"]
    lines += ["", "Answer the question using only the search results above, citing them."]
    return "\n".join(lines)


class AskWorkflow:
    def __init__(
        self,
        *,
        rewriter: QueryRewriter,
        store: ChunkStore,
        retriever: HybridRetriever,
        llm: BaseChatModel,
        model_name: str,
        min_score: float | None,
        system_prompt: str | None = None,
    ) -> None:
        self._rewriter = rewriter
        self._store = store
        self._retriever = retriever
        self._llm = llm
        self.model_name = model_name
        self.min_score = min_score  # None: no gate (the reranker is not calibrated)
        self._system_prompt = system_prompt or load_prompt("ask")

    @classmethod
    def from_settings(
        cls, settings: AISettings, *, store: ChunkStore, retriever: HybridRetriever
    ) -> "AskWorkflow":
        return cls(
            rewriter=QueryRewriter.from_settings(settings),
            store=store,
            retriever=retriever,
            llm=generation_model(
                settings,
                model=settings.ask_model,
                effort=settings.ask_effort,
                max_tokens=settings.ask_max_tokens,
                timeout_s=settings.ask_timeout_s,
            ),
            model_name=settings.ask_model,
            min_score=settings.gate_min_score,
        )

    async def run(
        self, request: OrchestratorRequest, trace: AskTrace | None = None
    ) -> AsyncIterator[WorkflowEvent]:
        trace = trace if trace is not None else AskTrace()
        document = request.document
        if document is None:
            trace.outcome = "needs_document"
            yield TokenEvent(NEEDS_DOCUMENT)
            yield DoneEvent("needs_document")
            return
        if await self._store.document(document.id) is None:
            raise DocumentNotIndexedError()

        # ---------------------------------------------------------------- pre-retrieval
        if request.history:
            yield StatusEvent("Understanding your follow-up question")
        trace.rewrite = await self._rewriter.rewrite(request.message, request.history)

        # ---------------------------------------------------------------- retrieval
        yield StatusEvent(f"Searching {document.name}")
        trace.retrieval = result = await self._retriever.retrieve(
            document_id=document.id, document_name=document.name, query=trace.rewrite.query
        )
        best = result.best_score
        if best is None or (self.min_score is not None and best < self.min_score):
            trace.gated = True
            trace.outcome = "not_found"
            log.info("ask_gated best_score=%s threshold=%s", best, self.min_score)
            yield TokenEvent(NOT_FOUND)
            yield DoneEvent("not_found")
            return

        # ---------------------------------------------------------------- generation
        yield StatusEvent("Writing the answer")
        chunks = [sc.chunk for sc in result.chunks]
        messages = build_messages(
            self._system_prompt,
            chunks,
            document_name=document.name,
            text=render_question(trace.rewrite),
        )
        trace.generation = GenerationTrace(requested_model=self.model_name)
        # When the user presses Stop, the model's stream closes at once.
        async with closing(
            stream_with_citations(
                self._llm,
                messages,
                chunks=chunks,
                trace=trace.generation,
                model_setting="LL_AI_ASK_MODEL",
            )
        ) as events:
            async for event in events:
                yield event

        generation = trace.generation
        if is_not_found(generation.text):
            trace.outcome = "not_found"
        else:
            trace.outcome = "answered"
            if not generation.citations:
                trace.warnings.append("uncited_answer")
                log.warning("uncited_answer model=%s", generation.model)
        if generation.stop_reason == "max_tokens":
            trace.warnings.append("truncated")
        yield DoneEvent(trace.outcome)
