from pathlib import Path

from legallens_ai.retrieval.chunker import chunk_pages
from legallens_ai.retrieval.models import (
    FastEmbedEmbedder,
    FastEmbedReranker,
    Qwen3Reranker,
    make_embedder,
    make_reranker,
)
from legallens_ai.retrieval_bench import (
    BenchDoc,
    BenchQuestion,
    chunk_spans,
    covers,
    recall_at,
    reciprocal_rank,
    split_paragraphs,
)
from legallens_ai.schemas import PageText

TEXT = "1. Term\n\nThis   Agreement lasts\nthree years.\n\n  \n2. Fees\n\nFees are due monthly.\n"


def test_split_paragraphs_keeps_original_character_spans() -> None:
    paragraphs = split_paragraphs(TEXT)
    assert [p.text for p in paragraphs] == [
        "1. Term",
        "This Agreement lasts three years.",
        "2. Fees",
        "Fees are due monthly.",
    ]
    for p in paragraphs:
        assert " ".join(TEXT[p.start : p.end].split()) == p.text


def test_chunk_spans_map_chunks_back_to_the_source() -> None:
    paragraphs = split_paragraphs(TEXT)
    chunks = chunk_pages("d", [PageText(1, [p.text for p in paragraphs])], target_words=6)
    spans = chunk_spans(chunks, paragraphs)
    for chunk in chunks:
        start, end = spans[chunk.chunk_id]
        assert " ".join(TEXT[start:end].split()) == " ".join(chunk.paragraphs)


def test_coverage_needs_half_of_the_shorter_span() -> None:
    assert covers((0, 100), (40, 60))  # gold span inside the chunk
    assert covers((50, 150), (0, 100))  # half of the chunk overlaps
    assert not covers((95, 300), (0, 100))  # only touches the edge
    assert not covers((200, 300), (0, 100))


def test_recall_and_mrr() -> None:
    doc = BenchDoc("d", "cuad", "n", [], {"a": (0, 50), "b": (50, 100), "c": (100, 150)})
    q = BenchQuestion("q", "cuad", "d", "?", ((60, 90), (110, 140)))
    assert recall_at(["a", "b", "c"], doc, q, 1) == 0.0
    assert recall_at(["a", "b", "c"], doc, q, 2) == 0.5
    assert recall_at(["c", "b"], doc, q, 2) == 1.0
    assert reciprocal_rank(["a", "c", "b"], doc, q) == 0.5
    assert reciprocal_rank(["a"], doc, q) == 0.0


def test_each_embedder_gets_its_documented_query_prefix(tmp_path: Path) -> None:
    qwen = make_embedder("Qwen/Qwen3-Embedding-0.6B", tmp_path)
    assert isinstance(qwen, FastEmbedEmbedder)
    assert qwen.query_prefix.startswith("Instruct: ") and qwen.query_prefix.endswith("\nQuery:")
    bge = make_embedder("BAAI/bge-base-en-v1.5", tmp_path)
    assert isinstance(bge, FastEmbedEmbedder)
    assert bge.query_prefix == "Represent this sentence for searching relevant passages: "
    assert bge.passage_prefix == ""
    none = make_embedder("BAAI/bge-base-en-v1.5", tmp_path, query_prefix="")
    assert isinstance(none, FastEmbedEmbedder) and none.query_prefix == ""


def test_reranker_backend_follows_the_model_id(tmp_path: Path) -> None:
    assert isinstance(make_reranker("Qwen/Qwen3-Reranker-0.6B", tmp_path), Qwen3Reranker)
    assert isinstance(make_reranker("BAAI/bge-reranker-v2-m3", tmp_path), FastEmbedReranker)


def test_gate_threshold_follows_the_reranker_unless_overridden() -> None:
    from legallens_ai.config import AISettings

    assert AISettings(reranker_model="BAAI/bge-reranker-v2-m3").gate_min_score == -7.0
    assert AISettings(reranker_model="Qwen/Qwen3-Reranker-0.6B").gate_min_score == 0.1
    assert AISettings(reranker_model="some/uncalibrated-model").gate_min_score is None
    override = AISettings(reranker_model="BAAI/bge-reranker-v2-m3", rerank_min_score=-3.0)
    assert override.gate_min_score == -3.0
