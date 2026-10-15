"""Chunking, indexing and hybrid retrieval. ``open_retrieval()`` wires it all from settings."""

from dataclasses import dataclass

from legallens_ai.config import AISettings
from legallens_ai.retrieval.chunk_store import ChunkStore
from legallens_ai.retrieval.hybrid import HybridRetriever
from legallens_ai.retrieval.indexer import DocumentIndexer
from legallens_ai.retrieval.models import Embedder, Reranker, make_embedder, make_reranker
from legallens_ai.retrieval.types import Chunk, IndexedDocument, RetrievalResult, ScoredChunk
from legallens_ai.retrieval.vector_store import QdrantVectorStore, VectorStore


@dataclass
class Retrieval:
    store: ChunkStore
    embedder: Embedder
    reranker: Reranker
    vectors: VectorStore
    indexer: DocumentIndexer
    retriever: HybridRetriever

    async def close(self) -> None:
        await self.vectors.close()


async def open_retrieval(settings: AISettings | None = None) -> Retrieval:
    """Builds the retrieval stack. Embedded Qdrant locks its folder: open one per process."""
    settings = settings or AISettings()
    store = ChunkStore(settings.chunk_db_path)
    embedder = make_embedder(
        settings.embedding_model, settings.models_dir, query_prefix=settings.embedding_query_prefix
    )
    reranker = make_reranker(settings.reranker_model, settings.models_dir)
    dimension = await embedder.dimension()
    if settings.qdrant_url:
        key = settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
        vectors: VectorStore = QdrantVectorStore(
            collection=settings.qdrant_collection,
            dimension=dimension,
            url=settings.qdrant_url,
            api_key=key,
        )
    else:
        vectors = QdrantVectorStore(
            collection=settings.qdrant_collection,
            dimension=dimension,
            path=settings.qdrant_path,
        )
    return Retrieval(
        store=store,
        embedder=embedder,
        reranker=reranker,
        vectors=vectors,
        indexer=DocumentIndexer(
            store,
            embedder,
            vectors,
            target_words=settings.chunk_target_words,
            max_words=settings.chunk_max_words,
        ),
        retriever=HybridRetriever(
            store,
            embedder,
            vectors,
            reranker,
            vector_k=settings.retrieval_vector_k,
            keyword_k=settings.retrieval_keyword_k,
            top_n=settings.retrieval_top_n,
        ),
    )


__all__ = [
    "Chunk",
    "ChunkStore",
    "DocumentIndexer",
    "HybridRetriever",
    "IndexedDocument",
    "Retrieval",
    "RetrievalResult",
    "ScoredChunk",
    "open_retrieval",
]
