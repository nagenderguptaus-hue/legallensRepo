"""Hybrid retrieval (W16-W20): vector top-K + BM25 top-K → union → cross-encoder → top N.

Both searches run concurrently on the (possibly rewritten) query. Their results are merged by
chunk id, with no score fusion: the reranker reads every candidate next to the query and
decides the order. Each result keeps its vector and BM25 rank so the eval can tell a recall
miss (never retrieved) from a ranking miss (retrieved, then ranked low).

Failures raise ``RetrievalUnavailableError``; there is no fallback to un-reranked results.
Logs carry ids, ranks and scores only, never text (NFR-5).
"""

import asyncio
import logging
import time

from legallens_ai.errors import OrchestratorError, RetrievalUnavailableError
from legallens_ai.retrieval.chunk_store import ChunkStore
from legallens_ai.retrieval.indexer import search_text
from legallens_ai.retrieval.models import Embedder, Reranker
from legallens_ai.retrieval.types import RetrievalResult, ScoredChunk
from legallens_ai.retrieval.vector_store import VectorStore

log = logging.getLogger("legallens_ai.retrieval")


class HybridRetriever:
    def __init__(
        self,
        store: ChunkStore,
        embedder: Embedder,
        vectors: VectorStore,
        reranker: Reranker,
        *,
        vector_k: int = 25,
        keyword_k: int = 25,
        top_n: int = 8,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._vectors = vectors
        self._reranker = reranker
        self.vector_k = vector_k
        self.keyword_k = keyword_k
        self.top_n = top_n

    async def retrieve(
        self, *, document_id: str, document_name: str, query: str
    ) -> RetrievalResult:
        timings: dict[str, float] = {}
        try:
            started = time.perf_counter()

            async def vector_search() -> list[str]:
                vector = await self._embedder.embed_query(query)
                return await self._vectors.search(document_id, vector, self.vector_k)

            vector_ids, keyword_ids = await asyncio.gather(
                vector_search(), self._store.keyword_search(document_id, query, self.keyword_k)
            )
            timings["search_ms"] = (time.perf_counter() - started) * 1000

            vector_rank = {cid: i for i, cid in enumerate(vector_ids, start=1)}
            keyword_rank = {cid: i for i, cid in enumerate(keyword_ids, start=1)}
            candidate_ids = list(dict.fromkeys([*vector_ids, *keyword_ids]))
            chunks = await self._store.get(candidate_ids)
            # A vector without a chunk row means the two stores disagree; skip it, don't fail.
            candidates = [chunks[cid] for cid in candidate_ids if cid in chunks]

            started = time.perf_counter()
            scores = await self._reranker.scores(
                query, [search_text(c, document_name) for c in candidates]
            )
            timings["rerank_ms"] = (time.perf_counter() - started) * 1000
        except OrchestratorError:
            raise
        except Exception as exc:
            log.warning("retrieval_failed document_id=%s error=%s", document_id, type(exc).__name__)
            raise RetrievalUnavailableError() from exc

        ranked = sorted(
            (
                ScoredChunk(
                    chunk=c,
                    rerank_score=s,
                    vector_rank=vector_rank.get(c.chunk_id),
                    keyword_rank=keyword_rank.get(c.chunk_id),
                )
                for c, s in zip(candidates, scores, strict=True)
            ),
            key=lambda sc: sc.rerank_score,
            reverse=True,
        )[: self.top_n]
        result = RetrievalResult(
            query=query,
            chunks=ranked,
            candidates=len(candidates),
            vector_hits=len(vector_ids),
            keyword_hits=len(keyword_ids),
            timings_ms=timings,
        )
        log.info(
            "retrieved document_id=%s vector=%d keyword=%d candidates=%d best=%s search_ms=%.0f "
            "rerank_ms=%.0f top=%s",
            document_id,
            result.vector_hits,
            result.keyword_hits,
            result.candidates,
            f"{result.best_score:.2f}" if result.best_score is not None else None,
            timings["search_ms"],
            timings["rerank_ms"],
            [
                (sc.chunk.chunk_id, sc.vector_rank, sc.keyword_rank, round(sc.rerank_score, 2))
                for sc in ranked
            ],
        )
        return result
