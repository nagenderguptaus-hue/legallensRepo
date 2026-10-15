"""Vector store (W13): Qdrant, embedded by default, or a Qdrant server when a URL is set.

Embedded mode keeps everything in ``<data_dir>/qdrant`` with no server process. Setting
``LL_AI_QDRANT_URL`` runs the same code against a server (e.g. the ``qdrant/qdrant`` Docker
image). Each point stores only ids: the chunk text lives in the SQLite chunk store.
"""

import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from qdrant_client import AsyncQdrantClient, models

from legallens_ai.errors import RetrievalUnavailableError


class VectorStore(Protocol):
    async def upsert(
        self, document_id: str, chunk_ids: Sequence[str], vectors: Sequence[Sequence[float]]
    ) -> None: ...

    async def search(self, document_id: str, vector: Sequence[float], k: int) -> list[str]:
        """Chunk ids of the document's nearest chunks, best first."""
        ...

    async def delete_document(self, document_id: str) -> None: ...

    async def close(self) -> None: ...


def point_id(chunk_id: str) -> str:
    """Qdrant ids must be UUIDs or integers; derive a stable UUID from the chunk id."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"legallens:{chunk_id}"))


def _document_filter(document_id: str) -> models.Filter:
    return models.Filter(
        must=[models.FieldCondition(key="document_id", match=models.MatchValue(value=document_id))]
    )


class QdrantVectorStore:
    def __init__(
        self,
        *,
        collection: str,
        dimension: int,
        path: Path | None = None,
        url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        if (path is None) == (url is None):
            raise ValueError("Pass exactly one of path (embedded) or url (server)")
        self.collection = collection
        self.dimension = dimension
        self._embedded = path is not None
        if path is not None:
            path.mkdir(parents=True, exist_ok=True)
            self._client = AsyncQdrantClient(path=str(path))
        else:
            self._client = AsyncQdrantClient(url=url, api_key=api_key)
        self._ready = False

    async def _ensure_collection(self) -> None:
        if self._ready:
            return
        if await self._client.collection_exists(self.collection):
            info = await self._client.get_collection(self.collection)
            params = info.config.params.vectors
            size = params.size if isinstance(params, models.VectorParams) else None
            if size != self.dimension:
                raise RetrievalUnavailableError(
                    f"The vector index was built with a different embedding model ({size} "
                    f"dimensions, now {self.dimension}). Re-index the documents."
                )
        else:
            await self._client.create_collection(
                self.collection,
                vectors_config=models.VectorParams(
                    size=self.dimension, distance=models.Distance.COSINE
                ),
            )
            if not self._embedded:  # payload indexes only exist on a server
                await self._client.create_payload_index(
                    self.collection, "document_id", models.PayloadSchemaType.KEYWORD
                )
        self._ready = True

    async def upsert(
        self, document_id: str, chunk_ids: Sequence[str], vectors: Sequence[Sequence[float]]
    ) -> None:
        if len(chunk_ids) != len(vectors):
            raise ValueError("chunk_ids and vectors differ in length")
        await self._ensure_collection()
        await self._client.upsert(
            self.collection,
            points=[
                models.PointStruct(
                    id=point_id(cid),
                    vector=list(vec),
                    payload={"document_id": document_id, "chunk_id": cid},
                )
                for cid, vec in zip(chunk_ids, vectors, strict=True)
            ],
        )

    async def search(self, document_id: str, vector: Sequence[float], k: int) -> list[str]:
        await self._ensure_collection()
        result = await self._client.query_points(
            self.collection,
            query=list(vector),
            query_filter=_document_filter(document_id),
            limit=k,
            with_payload=["chunk_id"],
        )
        return [str(p.payload["chunk_id"]) for p in result.points if p.payload]

    async def delete_document(self, document_id: str) -> None:
        await self._ensure_collection()
        await self._client.delete(
            self.collection,
            points_selector=models.FilterSelector(filter=_document_filter(document_id)),
        )

    async def close(self) -> None:
        await self._client.close()
