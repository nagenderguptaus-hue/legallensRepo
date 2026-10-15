"""Indexes a document's extracted pages: chunk → embed → vector store + chunk store (W21).

``index()`` is idempotent: indexing a document again replaces its earlier chunks and vectors.
The SQLite ``documents`` row is written last, so a document only counts as indexed once its
vectors are stored. ``purge()`` deletes both (FR-5), matching the backend's
``IngestionPipeline.purge``.
"""

import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Literal

from legallens_ai.errors import OrchestratorError, RetrievalUnavailableError
from legallens_ai.retrieval.chunk_store import ChunkStore
from legallens_ai.retrieval.chunker import chunk_pages
from legallens_ai.retrieval.models import Embedder
from legallens_ai.retrieval.types import Chunk, IndexedDocument
from legallens_ai.retrieval.vector_store import VectorStore
from legallens_ai.schemas import PageText

log = logging.getLogger("legallens_ai.indexer")

# progress(stage, current, total): same stage names as the backend's ingestion progress.
Progress = Callable[[Literal["chunking", "indexing"], int | None, int | None], Awaitable[None]]
EMBED_GROUP = 64  # chunks embedded per progress update


def search_text(chunk: Chunk, document_name: str) -> str:
    """What gets embedded and reranked: a short locating header, then the chunk text (W21b)."""
    where = " · ".join(p for p in (document_name, chunk.section, f"p. {chunk.page}") if p)
    return f"{where}\n\n{chunk.text}"


class DocumentIndexer:
    def __init__(
        self,
        store: ChunkStore,
        embedder: Embedder,
        vectors: VectorStore,
        *,
        target_words: int = 300,
        max_words: int = 380,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._vectors = vectors
        self._target_words = target_words
        self._max_words = max_words

    async def index(
        self,
        *,
        document_id: str,
        name: str,
        type: Literal["pdf", "docx"],
        pages: Sequence[PageText],
        progress: Progress | None = None,
    ) -> IndexedDocument:
        started = time.perf_counter()
        if progress:
            await progress("chunking", None, None)
        chunks = chunk_pages(
            document_id, pages, target_words=self._target_words, max_words=self._max_words
        )
        try:
            vectors: list[list[float]] = []
            for start in range(0, len(chunks), EMBED_GROUP):
                if progress:
                    await progress("indexing", start, len(chunks))
                group = chunks[start : start + EMBED_GROUP]
                vectors.extend(
                    await self._embedder.embed_passages([search_text(c, name) for c in group])
                )
            await self._vectors.delete_document(document_id)
            await self._vectors.upsert(document_id, [c.chunk_id for c in chunks], vectors)
            document = await self._store.replace_document(
                document_id=document_id, name=name, type=type, pages=len(pages), chunks=chunks
            )
        except OrchestratorError:
            raise
        except Exception as exc:
            log.warning("index_failed document_id=%s error=%s", document_id, exc.__class__.__name__)
            raise RetrievalUnavailableError("The document could not be indexed.") from exc
        if progress:
            await progress("indexing", len(chunks), len(chunks))
        log.info(
            "document_indexed document_id=%s pages=%d chunks=%d words=%d ms=%.0f",
            document_id,
            len(pages),
            len(chunks),
            document.words,
            (time.perf_counter() - started) * 1000,
        )
        return document

    async def purge(self, document_id: str) -> None:
        """Deletes the document's chunks and vectors. Safe to call for unknown documents."""
        try:
            await self._store.delete_document(document_id)
            await self._vectors.delete_document(document_id)
        except Exception as exc:
            log.warning("purge_failed document_id=%s error=%s", document_id, type(exc).__name__)
            raise RetrievalUnavailableError("The document's index could not be deleted.") from exc
