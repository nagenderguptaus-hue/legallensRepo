"""A stand-in for ``ChatAnthropic.with_structured_output(..., include_raw=True)``: no network."""

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.prompt_values import PromptValue
from langchain_core.runnables import RunnableLambda

from legallens_ai.schemas import Intent, IntentClassification


class FakeStructuredLLM:
    """Returns a scripted result (or raises) and records the messages it was sent."""

    def __init__(
        self,
        intent: Intent = "ask",
        rationale: str = "A specific question.",
        *,
        parsed: Any = "default",
        error: Exception | None = None,
        stop_reason: str = "end_turn",
    ) -> None:
        self.parsed = (
            IntentClassification(intent=intent, rationale=rationale)
            if parsed == "default"
            else parsed
        )
        self.error = error
        self.stop_reason = stop_reason
        self.calls: list[list[BaseMessage]] = []

    async def _respond(self, prompt: PromptValue) -> dict[str, Any]:
        self.calls.append(prompt.to_messages())
        if self.error is not None:
            raise self.error
        raw = AIMessage(
            content="{}",
            response_metadata={"stop_reason": self.stop_reason},
            usage_metadata={"input_tokens": 1200, "output_tokens": 40, "total_tokens": 1240},
        )
        failure = ValueError("bad output") if self.parsed is None else None
        return {"raw": raw, "parsed": self.parsed, "parsing_error": failure}

    def runnable(self) -> RunnableLambda[PromptValue, dict[str, Any]]:
        return RunnableLambda(self._respond)

    @property
    def last_user_turn(self) -> str:
        return str(self.calls[-1][-1].content)

    @property
    def last_system_prompt(self) -> str:
        return str(self.calls[-1][0].content)
