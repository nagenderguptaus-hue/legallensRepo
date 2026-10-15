"""The Summary workflow: the whole document, in FR-12's six sections, each cited (FR-13).

    every chunk, in reading order, as cited search results (prompt-cached)
      → model picked by length: Sonnet 5.5 up to ~60k tokens, Opus 5.5 above (W4)
      → streamed six-section markdown
      → check: all six headings present, each non-empty section cites something (W30)

Single pass, no map-reduce: any document within the BRD's 300-page limit fits the 1M-token
context. A document above ``max_document_tokens`` is refused with ``document_too_large`` (W29).
"""

import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

from langchain_core.language_models import BaseChatModel

from legallens_ai.config import AISettings
from legallens_ai.errors import DocumentNotIndexedError, DocumentTooLargeError
from legallens_ai.events import DoneEvent, StatusEvent, TokenEvent, WorkflowEvent
from legallens_ai.llm import generation_model
from legallens_ai.prompting import escape, load_prompt, render_history
from legallens_ai.retrieval.chunk_store import ChunkStore
from legallens_ai.schemas import OrchestratorRequest, Outcome
from legallens_ai.streams import closing
from legallens_ai.workflows.ask import NEEDS_DOCUMENT
from legallens_ai.workflows.checks import SectionCheck, check_summary
from legallens_ai.workflows.generation import (
    GenerationTrace,
    build_messages,
    stream_with_citations,
)

log = logging.getLogger("legallens_ai.summary")


@dataclass
class SummaryTrace:
    model: str | None = None
    estimated_tokens: int = 0
    generation: GenerationTrace | None = None
    sections: list[SectionCheck] = field(default_factory=list)
    outcome: Outcome | None = None
    warnings: list[str] = field(default_factory=list)


class SummaryWorkflow:
    def __init__(
        self,
        *,
        store: ChunkStore,
        llm_for: Callable[[str], BaseChatModel],
        short_model: str,
        long_model: str,
        long_threshold_tokens: int,
        max_document_tokens: int,
        history_turns: int = 4,
        turn_chars: int = 600,
        system_prompt: str | None = None,
    ) -> None:
        self._store = store
        self._llm_for = llm_for
        self.short_model = short_model
        self.long_model = long_model
        self.long_threshold_tokens = long_threshold_tokens
        self.max_document_tokens = max_document_tokens
        self._history_turns = history_turns
        self._turn_chars = turn_chars
        self._system_prompt = system_prompt or load_prompt("summary")

    @classmethod
    def from_settings(cls, settings: AISettings, *, store: ChunkStore) -> "SummaryWorkflow":
        def llm_for(model: str) -> BaseChatModel:
            return generation_model(
                settings,
                model=model,
                effort=settings.summary_effort,
                max_tokens=settings.summary_max_tokens,
                timeout_s=settings.summary_timeout_s,
            )

        return cls(
            store=store,
            llm_for=llm_for,
            short_model=settings.summary_model,
            long_model=settings.summary_long_model,
            long_threshold_tokens=settings.summary_long_threshold_tokens,
            max_document_tokens=settings.max_document_tokens,
        )

    def pick_model(self, estimated_tokens: int) -> str:
        return (
            self.long_model if estimated_tokens > self.long_threshold_tokens else self.short_model
        )

    def render_request(self, request: OrchestratorRequest) -> str:
        lines = render_history(
            request.history, turns=self._history_turns, turn_chars=self._turn_chars
        )
        lines += [
            "",
            "<lawyer_message>",
            escape(request.message.strip()),
            "</lawyer_message>",
            "",
            "Summarize the whole document above in the six required sections, citing every point.",
        ]
        return "\n".join(lines).lstrip()

    async def run(
        self, request: OrchestratorRequest, trace: SummaryTrace | None = None
    ) -> AsyncIterator[WorkflowEvent]:
        trace = trace if trace is not None else SummaryTrace()
        document = request.document
        if document is None:
            trace.outcome = "needs_document"
            yield TokenEvent(NEEDS_DOCUMENT)
            yield DoneEvent("needs_document")
            return
        indexed = await self._store.document(document.id)
        if indexed is None:
            raise DocumentNotIndexedError()
        trace.estimated_tokens = indexed.estimated_tokens
        if indexed.estimated_tokens > self.max_document_tokens:
            raise DocumentTooLargeError(
                f"{document.name} is too long to summarize in one pass "
                f"(~{indexed.estimated_tokens:,} tokens; limit {self.max_document_tokens:,})."
            )
        trace.model = model = self.pick_model(indexed.estimated_tokens)

        yield StatusEvent(f"Reading {document.name} ({indexed.pages} pages)")
        chunks = await self._store.chunks(document.id)
        messages = build_messages(
            self._system_prompt,
            chunks,
            document_name=document.name,
            text=self.render_request(request),
            cache_document=True,
        )
        yield StatusEvent("Writing the summary")
        trace.generation = GenerationTrace(requested_model=model)
        async with closing(
            stream_with_citations(
                self._llm_for(model),
                messages,
                chunks=chunks,
                trace=trace.generation,
                model_setting="LL_AI_SUMMARY_MODEL",
            )
        ) as events:
            async for event in events:
                yield event

        trace.sections = check_summary(trace.generation.text)
        for section in trace.sections:
            if not section.present:
                trace.warnings.append(f"missing_section:{section.heading}")
            elif not section.ok:
                trace.warnings.append(f"uncited_section:{section.heading}")
        if trace.generation.stop_reason == "max_tokens":
            trace.warnings.append("truncated")
        if trace.warnings:
            log.warning("summary_checks_failed warnings=%s", trace.warnings)
        trace.outcome = "answered"
        yield DoneEvent("answered")
