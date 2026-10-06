"""Test doubles for the two AI-layer ports."""

import asyncio
from collections.abc import AsyncIterator, Callable, Sequence

from legallens.adapters.standin.basic_ingestion import BasicIngestionPipeline
from legallens.ports.ingestion import IngestionInput, IngestionResult, ProgressReporter
from legallens.ports.orchestrator import (
    ChatContext,
    DoneEvent,
    IntentEvent,
    OrchestratorEvent,
    RuntimeHealth,
    TokenEvent,
)


class GatedPipeline(BasicIngestionPipeline):
    """Reports progress, then waits for ``gate`` before doing the real extraction."""

    def __init__(self) -> None:
        self.gate = asyncio.Event()
        self.started = asyncio.Event()
        self.cancelled = False
        self.purged: list[str] = []

    async def run(self, item: IngestionInput, progress: ProgressReporter) -> IngestionResult:
        await progress("extracting", 1, 3)
        self.started.set()
        try:
            await self.gate.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return await super().run(item, progress)

    async def purge(self, document_id: str) -> None:
        self.purged.append(document_id)


class FlakyPipeline(BasicIngestionPipeline):
    """Fails with an unexpected error ``failures`` times, then works."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    async def run(self, item: IngestionInput, progress: ProgressReporter) -> IngestionResult:
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("transient failure")
        return await super().run(item, progress)


class SlowPipeline(BasicIngestionPipeline):
    async def run(self, item: IngestionInput, progress: ProgressReporter) -> IngestionResult:
        await asyncio.sleep(10)
        raise AssertionError("unreachable")


class ScriptedOrchestrator:
    """Yields a fixed list of events (or the result of a callable), with optional pacing."""

    def __init__(
        self,
        events: Sequence[OrchestratorEvent]
        | Callable[[ChatContext], AsyncIterator[OrchestratorEvent]],
        *,
        delay: float = 0,
    ) -> None:
        self._events = events
        self._delay = delay
        self.contexts: list[ChatContext] = []

    async def health(self) -> RuntimeHealth:
        return RuntimeHealth(status="ready", model="scripted")

    async def stream(self, ctx: ChatContext) -> AsyncIterator[OrchestratorEvent]:
        self.contexts.append(ctx)
        if callable(self._events):
            async for event in self._events(ctx):
                yield event
            return
        for event in self._events:
            yield event
            if self._delay:
                await asyncio.sleep(self._delay)


async def endless_tokens(ctx: ChatContext) -> AsyncIterator[OrchestratorEvent]:
    """Answers forever, slowly, until cancelled (for stop/disconnect tests)."""
    yield IntentEvent("ask")
    n = 0
    while True:
        n += 1
        yield TokenEvent(f"word{n} ")
        await asyncio.sleep(0.01)


def simple_answer(text: str = "Hello there.") -> list[OrchestratorEvent]:
    return [IntentEvent("ask"), TokenEvent(text), DoneEvent("answered")]
