"""Data types shared by chunking, indexing and retrieval."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Chunk:
    """A run of whole paragraphs from one page. Never crosses a page, so citations are exact."""

    chunk_id: str
    document_id: str
    ordinal: int
    page: int
    section: str | None
    paragraphs: tuple[str, ...]

    @property
    def text(self) -> str:
        return "\n\n".join(self.paragraphs)

    @property
    def words(self) -> int:
        return sum(len(p.split()) for p in self.paragraphs)


@dataclass(frozen=True)
class IndexedDocument:
    id: str
    name: str
    type: Literal["pdf", "docx"]
    pages: int
    chunks: int
    words: int
    indexed_at: str

    @property
    def estimated_tokens(self) -> int:
        """Rough Claude token count (~1.35 tokens per English word of legal prose)."""
        return int(self.words * 1.35)


@dataclass(frozen=True)
class ScoredChunk:
    """A retrieved chunk with where it came from: ranks are 1-based, None = not in that list."""

    chunk: Chunk
    rerank_score: float
    vector_rank: int | None
    keyword_rank: int | None


@dataclass(frozen=True)
class RetrievalResult:
    query: str
    chunks: list[ScoredChunk]  # best first, at most top_n
    candidates: int  # union size sent to the reranker
    vector_hits: int
    keyword_hits: int
    timings_ms: dict[str, float]

    @property
    def best_score(self) -> float | None:
        return self.chunks[0].rerank_score if self.chunks else None
