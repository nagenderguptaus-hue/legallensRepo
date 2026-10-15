"""Intent classifier: one Claude call through LangChain, constrained to the four intents.

Chain (LCEL): ``ChatPromptTemplate`` (system prompt from ``intent_classifier.prompt.md`` + the
message and recent history) → ``ChatAnthropic.with_structured_output(method="json_schema")``.
Native structured outputs mean the API itself only lets the model return a valid
``IntentClassification``; anything else (a refusal, a truncated reply) is reported as
``IntentUnparseableError`` rather than guessed at.

Only metadata is logged (intent, latency, tokens), never the message text (NFR-5).
"""

import logging
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import anthropic
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable

from legallens_ai.config import AISettings
from legallens_ai.errors import IntentUnparseableError
from legallens_ai.llm import map_anthropic_error, require_api_key
from legallens_ai.prompting import (
    PROMPTS_DIR,
    TRUNCATED,
    escape,
    load_prompt,
    render_history,
)
from legallens_ai.schemas import ClassifierResult, IntentClassification, TokenUsage, Turn

log = logging.getLogger("legallens_ai.intent")

PROMPT_PATH = PROMPTS_DIR / "intent_classifier.prompt.md"
__all__ = ["PROMPT_PATH", "TRUNCATED", "IntentClassifier", "load_system_prompt", "render_user_turn"]


def load_system_prompt(path: Path = PROMPT_PATH) -> str:
    return load_prompt(path)


def render_user_turn(
    message: str, history: Sequence[Turn], *, history_turns: int, turn_chars: int
) -> str:
    lines = render_history(history, turns=history_turns, turn_chars=turn_chars)
    if lines:
        lines.append("")
    else:
        lines.append("There are no earlier turns in this conversation.")
        lines.append("")
    lines.append("<latest_message>")
    lines.append(escape(message.strip()))
    lines.append("</latest_message>")
    lines.append("")
    lines.append("Classify the intent of the latest message.")
    return "\n".join(lines)


class IntentClassifier:
    """Classifies one message. Build it with ``from_settings()``; tests pass a fake ``llm``.

    ``llm`` is a structured-output runnable that returns LangChain's ``include_raw`` dict:
    ``{"raw": AIMessage, "parsed": IntentClassification | None, "parsing_error": ...}``.
    """

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
                # A message object, not a template: braces in the prompt file are kept as text.
                SystemMessage(content=system_prompt or load_system_prompt()),
                ("human", "{input}"),
            ]
        )
        self._chain: Runnable[dict[str, str], dict[str, Any]] = prompt | llm

    @classmethod
    def from_settings(cls, settings: AISettings | None = None) -> "IntentClassifier":
        settings = settings or AISettings()
        chat = ChatAnthropic(
            model=settings.intent_model,
            api_key=require_api_key(settings),
            temperature=settings.intent_temperature,
            max_tokens=settings.intent_max_tokens,
            timeout=settings.intent_timeout_s,
            max_retries=settings.intent_max_retries,
        )
        structured = chat.with_structured_output(
            IntentClassification, method="json_schema", include_raw=True
        )
        return cls(
            structured,  # type: ignore[arg-type]  # include_raw=True always yields a dict
            model_name=settings.intent_model,
            history_turns=settings.intent_history_turns,
            turn_chars=settings.intent_turn_chars,
        )

    def render(self, message: str, history: Sequence[Turn] = ()) -> str:
        """The exact user turn sent to the model (handy for debugging the prompt)."""
        return render_user_turn(
            message, history, history_turns=self._history_turns, turn_chars=self._turn_chars
        )

    async def classify(self, message: str, history: Sequence[Turn] = ()) -> ClassifierResult:
        if not message.strip():
            raise ValueError("message must not be empty")
        started = time.perf_counter()
        try:
            out = await self._chain.ainvoke({"input": self.render(message, history)})
        except anthropic.APIError as exc:
            raise map_anthropic_error(
                exc, log=log, event="intent_model", model_setting="LL_AI_INTENT_MODEL"
            ) from exc
        latency_ms = (time.perf_counter() - started) * 1000

        raw = out.get("raw")
        parsed = out.get("parsed")
        usage = _usage(raw)
        if not isinstance(parsed, IntentClassification):
            stop_reason = raw.response_metadata.get("stop_reason") if raw is not None else None
            error = out.get("parsing_error")
            log.warning(
                "intent_unparseable stop_reason=%s error=%s",
                stop_reason,
                type(error).__name__ if error else None,
            )
            raise IntentUnparseableError()

        log.info(
            "intent_classified intent=%s latency_ms=%.0f input_tokens=%d output_tokens=%d model=%s",
            parsed.intent,
            latency_ms,
            usage.input_tokens,
            usage.output_tokens,
            self.model_name,
        )
        return ClassifierResult(
            intent=parsed.intent,
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
