"""Offline stand-ins for the retrieval models, the vector store and a streaming chat model."""

import hashlib
import math
import re
from collections.abc import AsyncIterator, Sequence
from typing import Any

from langchain_core.messages import AIMessageChunk, BaseMessage

_WORD = re.compile(r"[a-z0-9]+")


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


class FakeEmbedder:
    """Hashed bag of words: texts sharing words get similar vectors. No model download."""

    model_name = "fake-embedder"
    dim = 64

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for word in _words(text):
            vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    async def dimension(self) -> int:
        return self.dim

    async def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        if self.fail:
            raise RuntimeError("embedding model crashed")
        return [self._vector(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        if self.fail:
            raise RuntimeError("embedding model crashed")
        return self._vector(text)


class FakeReranker:
    """Score = number of query words found in the text, minus 10 (so no overlap is -10)."""

    model_name = "fake-reranker"

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    async def scores(self, query: str, texts: Sequence[str]) -> list[float]:
        self.calls.append((query, list(texts)))
        query_words = set(_words(query))
        return [float(len(query_words & set(_words(t)))) - 10.0 for t in texts]


class InMemoryVectorStore:
    def __init__(self) -> None:
        self.points: dict[str, tuple[str, list[float]]] = {}  # chunk_id -> (document_id, vec)

    async def upsert(
        self, document_id: str, chunk_ids: Sequence[str], vectors: Sequence[Sequence[float]]
    ) -> None:
        for cid, vec in zip(chunk_ids, vectors, strict=True):
            self.points[cid] = (document_id, list(vec))

    async def search(self, document_id: str, vector: Sequence[float], k: int) -> list[str]:
        scored = [
            (sum(a * b for a, b in zip(vec, vector, strict=True)), cid)
            for cid, (doc, vec) in self.points.items()
            if doc == document_id
        ]
        return [cid for _, cid in sorted(scored, reverse=True)[:k]]

    async def delete_document(self, document_id: str) -> None:
        self.points = {c: p for c, p in self.points.items() if p[0] != document_id}

    async def close(self) -> None:
        pass


def text_chunk(
    index: int, text: str = "", citations: list[dict[str, Any]] | None = None
) -> AIMessageChunk:
    block: dict[str, Any] = {"type": "text", "text": text, "index": index}
    if citations:
        block["citations"] = citations
    return AIMessageChunk(content=[block])


def citation(source: str, start: int = 0, end: int = 1, text: str = "quoted") -> dict[str, Any]:
    return {
        "type": "search_result_location",
        "source": source,
        "title": "t",
        "cited_text": text,
        "search_result_index": 0,
        "start_block_index": start,
        "end_block_index": end,
    }


def final_chunk(
    stop_reason: str = "end_turn", model: str = "claude-sonnet-5-5", output_tokens: int = 50
) -> AIMessageChunk:
    return AIMessageChunk(
        content=[],
        response_metadata={"stop_reason": stop_reason, "model_name": model},
        usage_metadata={"input_tokens": 1000, "output_tokens": output_tokens, "total_tokens": 1050},
    )


class FakeStreamingLLM:
    """Replays scripted ``AIMessageChunk``s from ``astream`` and records what it was sent."""

    def __init__(self, chunks: list[AIMessageChunk] | None = None, error: Exception | None = None):
        self.chunks = chunks if chunks is not None else [text_chunk(0, "An answer."), final_chunk()]
        self.error = error
        self.calls: list[list[BaseMessage]] = []

    async def astream(self, messages: list[BaseMessage], **_: Any) -> AsyncIterator[AIMessageChunk]:
        self.calls.append(messages)
        for chunk in self.chunks:
            yield chunk
        if self.error is not None:
            raise self.error

    @property
    def last_blocks(self) -> list[dict[str, Any]]:
        content = self.calls[-1][-1].content
        assert isinstance(content, list)
        return [b for b in content if isinstance(b, dict)]

    @property
    def last_text(self) -> str:
        return str(self.last_blocks[-1]["text"])
