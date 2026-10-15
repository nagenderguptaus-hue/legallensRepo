"""The Draft workflow: a memo, case brief or free-form draft (FR-15-FR-17), Opus 5.5.

instructions + recent history (the previous draft in full, for revisions — W36)
  + the whole reference document as cited search results, if one is selected (W34)
  → Opus infers the draft type and writes it, streamed (W33)
  → check: placeholders counted; legal citations found in neither the instructions,
    the conversation nor the document reported as invented (W37)
"""

import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field

from langchain_core.language_models import BaseChatModel

from legallens_ai.config import AISettings
from legallens_ai.errors import DocumentNotIndexedError, DocumentTooLargeError
from legallens_ai.events import DoneEvent, StatusEvent, WorkflowEvent
from legallens_ai.llm import generation_model
from legallens_ai.prompting import escape, load_prompt, render_history
from legallens_ai.retrieval.chunk_store import ChunkStore
from legallens_ai.retrieval.types import Chunk
from legallens_ai.schemas import OrchestratorRequest, Outcome, Turn
from legallens_ai.streams import closing
from legallens_ai.workflows.checks import DraftCheck, check_draft
from legallens_ai.workflows.generation import (
    GenerationTrace,
    build_messages,
    stream_with_citations,
)

log = logging.getLogger("legallens_ai.draft")


@dataclass
class DraftTrace:
    reference_chunks: int = 0
    revising: bool = False
    generation: GenerationTrace | None = None
    check: DraftCheck | None = None
    outcome: Outcome | None = None
    warnings: list[str] = field(default_factory=list)


def last_draft_index(history: Sequence[Turn]) -> int | None:
    """Index of the most recent assistant draft, kept whole so revisions see all of it."""
    for index in range(len(history) - 1, -1, -1):
        turn = history[index]
        if turn.role == "assistant" and turn.intent == "draft":
            return index
    return None


class DraftWorkflow:
    def __init__(
        self,
        *,
        store: ChunkStore,
        llm: BaseChatModel,
        model_name: str,
        max_document_tokens: int,
        history_turns: int = 6,
        turn_chars: int = 1_500,
        system_prompt: str | None = None,
    ) -> None:
        self._store = store
        self._llm = llm
        self.model_name = model_name
        self.max_document_tokens = max_document_tokens
        self._history_turns = history_turns
        self._turn_chars = turn_chars
        self._system_prompt = system_prompt or load_prompt("draft")

    @classmethod
    def from_settings(cls, settings: AISettings, *, store: ChunkStore) -> "DraftWorkflow":
        return cls(
            store=store,
            llm=generation_model(
                settings,
                model=settings.draft_model,
                effort=settings.draft_effort,
                max_tokens=settings.draft_max_tokens,
                timeout_s=settings.draft_timeout_s,
            ),
            model_name=settings.draft_model,
            max_document_tokens=settings.max_document_tokens,
            history_turns=settings.draft_history_turns,
            turn_chars=settings.draft_turn_chars,
        )

    def render_request(self, request: OrchestratorRequest, *, has_document: bool) -> str:
        history = list(request.history)
        draft_index = last_draft_index(history)
        # Always include the draft being revised, even if it is older than the turn window.
        turns = self._history_turns
        if draft_index is not None:
            turns = max(turns, len(history) - draft_index)
        lines = render_history(
            history, turns=turns, turn_chars=self._turn_chars, full_turn_index=draft_index
        )
        lines += [
            "",
            "<instructions>",
            escape(request.message.strip()),
            "</instructions>",
            "",
            (
                "Write the draft. The reference document is in the search results above."
                if has_document
                else "Write the draft. No reference document was provided: every fact must "
                "come from the instructions or the conversation."
            ),
        ]
        return "\n".join(lines).lstrip()

    async def run(
        self, request: OrchestratorRequest, trace: DraftTrace | None = None
    ) -> AsyncIterator[WorkflowEvent]:
        trace = trace if trace is not None else DraftTrace()
        document = request.document
        chunks: list[Chunk] = []
        if document is not None:
            indexed = await self._store.document(document.id)
            if indexed is None:
                raise DocumentNotIndexedError()
            if indexed.estimated_tokens > self.max_document_tokens:
                raise DocumentTooLargeError(
                    f"{document.name} is too long to use as a reference "
                    f"(~{indexed.estimated_tokens:,} tokens; limit {self.max_document_tokens:,})."
                )
            yield StatusEvent(f"Reading {document.name}")
            chunks = await self._store.chunks(document.id)
        trace.reference_chunks = len(chunks)
        trace.revising = last_draft_index(request.history) is not None

        text = self.render_request(request, has_document=bool(chunks))
        messages = build_messages(
            self._system_prompt,
            chunks,
            document_name=document.name if document else "",
            text=text,
            cache_document=bool(chunks),
        )
        yield StatusEvent("Revising the draft" if trace.revising else "Drafting")
        trace.generation = GenerationTrace(requested_model=self.model_name)
        async with closing(
            stream_with_citations(
                self._llm,
                messages,
                chunks=chunks,
                trace=trace.generation,
                model_setting="LL_AI_DRAFT_MODEL",
            )
        ) as events:
            async for event in events:
                yield event

        sources = [request.message, *(t.content for t in request.history)]
        sources += [c.text for c in chunks]
        trace.check = check_draft(trace.generation.text, sources)
        if trace.check.invented_citations:
            trace.warnings.append("invented_citation")
            log.warning("draft_invented_citations count=%d", len(trace.check.invented_citations))
        if trace.generation.stop_reason == "max_tokens":
            trace.warnings.append("truncated")
        trace.outcome = "answered"
        yield DoneEvent("answered")
