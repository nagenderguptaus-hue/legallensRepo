"""One process's AI-layer state, for an app that embeds this package (the backend).

Embedded Qdrant locks its folder, so a process must open the retrieval stack once and share
it: ingestion writes through it now, and the AI orchestrator will search through the same one.
Everything opens lazily on first use, inside the running event loop.
"""

import asyncio

from legallens_ai.config import AISettings
from legallens_ai.ingestion import DocumentIngestor, OcrEngine, make_ingestor
from legallens_ai.retrieval import Retrieval, open_retrieval


class AIRuntime:
    def __init__(
        self,
        settings: AISettings,
        *,
        retrieval: Retrieval | None = None,
        ocr: OcrEngine | None = None,
    ) -> None:
        """``retrieval`` / ``ocr`` replace the configured ones (tests, other model stacks)."""
        self.settings = settings
        self._retrieval = retrieval
        self._ocr = ocr
        self._ingestor: DocumentIngestor | None = None
        self._lock = asyncio.Lock()

    async def retrieval(self) -> Retrieval:
        async with self._lock:
            if self._retrieval is None:
                self._retrieval = await open_retrieval(self.settings)
            return self._retrieval

    async def ingestor(self) -> DocumentIngestor:
        if self._ingestor is None:
            retrieval = await self.retrieval()
            self._ingestor = make_ingestor(self.settings, retrieval, ocr=self._ocr)
        return self._ingestor

    async def close(self) -> None:
        async with self._lock:
            if self._retrieval is not None:
                await self._retrieval.close()
            self._retrieval = None
            self._ingestor = None
