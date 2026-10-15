"""Pre-retrieval: turns a follow-up question into a standalone search query (W7-W11).

Two guardrails are enforced in code, not left to the model:
1. No history → no model call; the question is searched as is (W7).
2. The model only *classifies* the relation. If it says ``standalone``, the original question
   is used verbatim and any text the model wrote is ignored (W8).

The prompt (``prompts/query_rewriter.prompt.md``) states both rules too, plus the rewrite rules
for real follow-ups. Same LCEL pattern as the intent router: Claude Haiku 4.5 with native
structured output. Logs carry metadata only, never the question (NFR-5).
"""

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import anthropic
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from pydantic import BaseModel, ConfigDict, Field

from legallens_ai.config import AISettings
from legallens_ai.errors import RewriteUnparseableError
from legallens_ai.llm import map_anthropic_error, require_api_key
from legallens_ai.prompting import escape, load_prompt, render_history
from legallens_ai.schemas import TokenUsage, Turn

log = logging.getLogger("legallens_ai.rewrite")

RewriteReason = Literal["no_history", "standalone", "rewritten"]


# Sent to Claude as the output JSON schema; descriptions are written for the model.
class QueryRewrite(BaseModel):
    """Whether the latest question depends on the conversation, and the standalone query."""

    model_config = ConfigDict(extra="forbid")

    rationale: str = Field(
        description="One short sentence: does the question depend on the history, and what "
        "was resolved?"
    )
    relation: Literal["standalone", "follow_up"] = Field(
        description="standalone if the question can be understood on its own; follow_up if it "
        "needs the earlier turns."
    )
    standalone_query: str = Field(
        description="standalone: the latest question unchanged. follow_up: the question "
        "rewritten to stand on its own."
    )


@dataclass(frozen=True)
class RewriteResult:
    query: str  # what retrieval searches for
    original: str
    reason: RewriteReason
    rationale: str = ""
    model: str | None = None  # None when no model was called
    latency_ms: float = 0.0
    usage: TokenUsage = field(default_factory=TokenUsage)

    @property
    def rewritten(self) -> bool:
        return self.reason == "rewritten"


def render_rewrite_turn(
    question: str, history: Sequence[Turn], *, history_turns: int, turn_chars: int
) -> str:
    lines = render_history(history, turns=history_turns, turn_chars=turn_chars)
    lines += [
        "",
        "<latest_question>",
        escape(question.strip()),
        "</latest_question>",
        "",
        "Decide whether the latest question depends on the conversation history, and give the "
        "standalone query.",
    ]
    return "\n".join(lines).lstrip()


class QueryRewriter:
    """Build with ``from_settings()``; tests pass a fake structured-output ``llm``."""

    def __init__(
        self,
        llm: Runnable[Any, dict[str, Any]],
        *,
        model_name: str,
        system_prompt: str | None = None,
        history_turns: int = 6,
        turn_chars: int = 600,
    ) -> None:
        self.model_name = model_name
        self._history_turns = history_turns
        self._turn_chars = turn_chars
        prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessage(content=system_prompt or load_prompt("query_rewriter")),
                ("human", "{input}"),
            ]
        )
        self._chain: Runnable[dict[str, str], dict[str, Any]] = prompt | llm

    @classmethod
    def from_settings(cls, settings: AISettings | None = None) -> "QueryRewriter":
        settings = settings or AISettings()
        chat = ChatAnthropic(
            model=settings.rewrite_model,
            api_key=require_api_key(settings),
            temperature=0.0,
            max_tokens=settings.rewrite_max_tokens,
            timeout=settings.rewrite_timeout_s,
            max_retries=settings.generation_max_retries,
        )
        structured = chat.with_structured_output(
            QueryRewrite, method="json_schema", include_raw=True
        )
        return cls(
            structured,  # type: ignore[arg-type]  # include_raw=True always yields a dict
            model_name=settings.rewrite_model,
            history_turns=settings.rewrite_history_turns,
            turn_chars=settings.rewrite_turn_chars,
        )

    def render(self, question: str, history: Sequence[Turn] = ()) -> str:
        return render_rewrite_turn(
            question, history, history_turns=self._history_turns, turn_chars=self._turn_chars
        )

    async def rewrite(self, question: str, history: Sequence[Turn] = ()) -> RewriteResult:
        question = question.strip()
        if not question:
            raise ValueError("question must not be empty")
        # Guardrail 1 (W7): nothing to resolve against, so nothing to rewrite.
        if self._history_turns <= 0 or not history:
            log.info("rewrite_skipped reason=no_history")
            return RewriteResult(query=question, original=question, reason="no_history")

        started = time.perf_counter()
        try:
            out = await self._chain.ainvoke({"input": self.render(question, history)})
        except anthropic.APIError as exc:
            raise map_anthropic_error(
                exc, log=log, event="rewrite_model", model_setting="LL_AI_REWRITE_MODEL"
            ) from exc
        latency_ms = (time.perf_counter() - started) * 1000

        raw = out.get("raw")
        parsed = out.get("parsed")
        usage = _usage(raw)
        if not isinstance(parsed, QueryRewrite):
            stop_reason = raw.response_metadata.get("stop_reason") if raw is not None else None
            log.warning("rewrite_unparseable stop_reason=%s", stop_reason)
            raise RewriteUnparseableError()

        rewritten = " ".join(parsed.standalone_query.split())
        # Guardrail 2 (W8): the model classifies; code decides. Standalone → original verbatim.
        if parsed.relation == "standalone" or not rewritten:
            reason: RewriteReason = "standalone"
            query = question
        else:
            reason = "rewritten"
            query = rewritten
        log.info(
            "rewrite_done reason=%s latency_ms=%.0f input_tokens=%d output_tokens=%d model=%s",
            reason,
            latency_ms,
            usage.input_tokens,
            usage.output_tokens,
            self.model_name,
        )
        return RewriteResult(
            query=query,
            original=question,
            reason=reason,
            rationale=parsed.rationale,
            model=self.model_name,
            latency_ms=latency_ms,
            usage=usage,
        )


def _usage(raw: object) -> TokenUsage:
    if isinstance(raw, AIMessage) and raw.usage_metadata:
        return TokenUsage(
            input_tokens=raw.usage_metadata.get("input_tokens", 0),
            output_tokens=raw.usage_metadata.get("output_tokens", 0),
        )
    return TokenUsage()
