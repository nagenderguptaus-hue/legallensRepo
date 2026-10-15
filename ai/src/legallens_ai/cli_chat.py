"""``legallens-ai chat``: the full chat turn the backend runs, from the terminal.

legallens-ai chat --doc <id>                 interactive, follow-ups keep history
legallens-ai chat --doc <id> "Summarize it"  one message
legallens-ai chat "Draft a demand letter"    no document selected

Each turn goes through ``ChatEngine`` → ``Orchestrator.stream()`` exactly as in the app: the
router picks the intent, the matching workflow answers, and the turn's trace (models, tokens,
timings, warnings; metadata only) is printed after the answer.
"""

import argparse
from collections.abc import AsyncIterator

from legallens_ai.cli_workflows import _chat_loop, _document, _render, _say
from legallens_ai.config import AISettings
from legallens_ai.engine import ChatEngine
from legallens_ai.events import IntentEvent, OrchestratorEvent, WorkflowEvent
from legallens_ai.orchestrator import TurnTrace
from legallens_ai.runtime import AIRuntime
from legallens_ai.schemas import DocumentInfo, Intent, OrchestratorRequest, Turn


async def _workflow_events(
    events: AsyncIterator[OrchestratorEvent], intent: list[Intent]
) -> AsyncIterator[WorkflowEvent]:
    async for event in events:
        if isinstance(event, IntentEvent):
            intent.append(event.intent)
            _say(f"intent: {event.intent}")
        else:
            yield event


def _trace_line(trace: TurnTrace) -> None:
    fields = {k: v for k, v in trace.metadata().items() if v not in (None, [], "")}
    _say("trace: " + " ".join(f"{k}={v}" for k, v in fields.items()))


async def chat(args: argparse.Namespace, settings: AISettings) -> int:
    runtime = AIRuntime(settings)
    engine = ChatEngine(runtime)
    try:
        doc: DocumentInfo | None = None
        if args.doc:
            doc = await _document(await runtime.retrieval(), args.doc)

        async def one(message: str, history: list[Turn]) -> tuple[str, Intent]:
            trace = TurnTrace()
            intent: list[Intent] = []
            request = OrchestratorRequest(message=message, history=history, document=doc)
            try:
                answer = await _render(_workflow_events(engine.stream(request, trace), intent))
            finally:
                _trace_line(trace)
            return answer, intent[0] if intent else "clarify"

        return await _chat_loop(" ".join(args.message) or None, one)
    finally:
        await engine.close()
        await runtime.close()


def add_parser(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = sub.add_parser("chat", help="full chat turns: router → Ask / Summary / Draft / Clarify")
    p.add_argument("message", nargs="*", help="the message (omit for interactive mode)")
    p.add_argument("--doc", help="id of an indexed document to select (see `docs`)")
