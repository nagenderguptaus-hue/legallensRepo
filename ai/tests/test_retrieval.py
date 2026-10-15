from pathlib import Path

import pytest

from legallens_ai.errors import RetrievalUnavailableError
from legallens_ai.retrieval.chunk_store import ChunkStore, fts_query
from legallens_ai.retrieval.chunker import chunk_pages, is_heading
from legallens_ai.retrieval.hybrid import HybridRetriever
from legallens_ai.retrieval.indexer import DocumentIndexer, search_text
from legallens_ai.retrieval.loaders import load_document
from legallens_ai.schemas import PageText
from tests.workflow_fakes import FakeEmbedder, FakeReranker, InMemoryVectorStore

EVAL_DOCS = Path(__file__).resolve().parents[1] / "evals" / "documents"


def words(n: int, word: str = "lorem") -> str:
    return " ".join([word] * n) + "."


# ---------------------------------------------------------------- chunker


def test_chunks_never_cross_pages_and_keep_paragraphs_whole() -> None:
    pages = [
        PageText(1, ["1. Rent", words(40), words(40)]),
        PageText(2, [words(40), "2. Deposit", words(40)]),
    ]
    chunks = chunk_pages("d", pages, target_words=300, max_words=380)
    assert [c.page for c in chunks] == [1, 2]
    assert chunks[0].paragraphs == ("1. Rent", words(40), words(40))
    assert [c.chunk_id for c in chunks] == ["d:00000", "d:00001"]


def test_paragraphs_are_packed_up_to_the_target() -> None:
    pages = [PageText(1, [words(60) for _ in range(5)])]
    chunks = chunk_pages("d", pages, target_words=130, max_words=200)
    assert [len(c.paragraphs) for c in chunks] == [2, 2, 1]
    assert all(c.words <= 130 for c in chunks)


def test_long_paragraph_is_split_at_sentences_within_max() -> None:
    sentence = "The Tenant shall pay rent on time and in full. "
    pages = [PageText(1, [sentence * 30])]  # 300 words, 30 sentences
    chunks = chunk_pages("d", pages, target_words=60, max_words=100)
    assert len(chunks) > 1
    assert all(c.words <= 100 for c in chunks)
    assert all(p.endswith(".") for c in chunks for p in c.paragraphs)


def test_a_heading_is_never_left_at_the_end_of_a_chunk() -> None:
    pages = [PageText(1, [words(90), "5. Early Termination", words(90)])]
    chunks = chunk_pages("d", pages, target_words=100, max_words=200)
    assert chunks[0].paragraphs == (words(90),)
    assert chunks[1].paragraphs[0] == "5. Early Termination"
    assert chunks[1].section == "5. Early Termination"


def test_section_carries_over_from_earlier_pages() -> None:
    pages = [
        PageText(1, ["7. Maintenance", words(20)], section="7. Maintenance"),
        PageText(2, [words(20)], section="7. Maintenance"),
    ]
    chunks = chunk_pages("d", pages)
    assert [c.section for c in chunks] == ["7. Maintenance", "7. Maintenance"]


def test_empty_pages_make_no_chunks() -> None:
    assert chunk_pages("d", [PageText(1, []), PageText(2, ["  "])]) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("5. Early Termination", True),
        ("ARTICLE IV CONFIDENTIALITY", True),
        ("COMMERCIAL LEASE AGREEMENT", True),
        ("Tenant shall pay rent.", False),
        ("1.4 Order Form means an ordering document signed by both Parties.", False),
    ],
)
def test_heading_detection(text: str, expected: bool) -> None:
    assert is_heading(text) is expected


def test_search_text_has_a_locating_header() -> None:
    chunk = chunk_pages("d", [PageText(3, ["5. Early Termination", "Tenant may end it."])])[0]
    assert search_text(chunk, "Lease.pdf").startswith("Lease.pdf · 5. Early Termination · p. 3\n\n")


# ---------------------------------------------------------------- FTS5 query building


def test_fts_query_quotes_terms_and_drops_stopwords() -> None:
    assert fts_query("What is the late fee for the Tenant?") == '"late" OR "fee" OR "tenant"'


@pytest.mark.parametrize(
    "hostile", ['"OR NEAR(x*) : -- drop', "rent* AND NOT deposit", "col:value ^start", "'; DROP"]
)
def test_fts_query_neutralises_query_syntax(hostile: str) -> None:
    query = fts_query(hostile)
    assert query is not None
    for term in query.split(" OR "):
        assert term.startswith('"') and term.endswith('"')
        assert '"' not in term[1:-1]


def test_fts_query_of_only_stopwords_is_none() -> None:
    assert fts_query("what is it?") is None


# ---------------------------------------------------------------- chunk store


def _pages() -> list[PageText]:
    return [
        PageText(1, ["1. Rent", "Tenant shall pay monthly Base Rent of $4,500."], "1. Rent"),
        PageText(2, ["2. Deposit", "Tenant shall deposit $9,000 as security."], "2. Deposit"),
        PageText(
            3, ["3. Termination", "Tenant may terminate early with notice."], "3. Termination"
        ),
    ]


async def test_store_round_trip_and_keyword_search(tmp_path: Path) -> None:
    store = ChunkStore(tmp_path / "chunks.db")
    chunks = chunk_pages("doc_a", _pages())
    await store.replace_document(
        document_id="doc_a", name="A.pdf", type="pdf", pages=3, chunks=chunks
    )
    other = chunk_pages("doc_b", [PageText(1, ["Deposit terms for another document."])])
    await store.replace_document(
        document_id="doc_b", name="B.pdf", type="pdf", pages=1, chunks=other
    )

    doc = await store.document("doc_a")
    assert doc is not None and doc.chunks == 3 and doc.pages == 3
    assert [c.page for c in await store.chunks("doc_a")] == [1, 2, 3]
    hits = await store.keyword_search("doc_a", "How big is the security deposit?", 5)
    assert hits[0] == "doc_a:00001"
    assert all(h.startswith("doc_a:") for h in hits)  # never another document's chunks
    assert await store.keyword_search("doc_a", "what is it?", 5) == []
    assert await store.keyword_search("doc_a", '"OR NEAR(x*) : --', 5) == []  # no syntax error


async def test_reindexing_replaces_and_delete_clears_the_keyword_index(tmp_path: Path) -> None:
    store = ChunkStore(tmp_path / "chunks.db")
    chunks = chunk_pages("doc_a", _pages())
    await store.replace_document(document_id="doc_a", name="A", type="pdf", pages=3, chunks=chunks)
    fewer = chunk_pages("doc_a", _pages()[:1])
    await store.replace_document(document_id="doc_a", name="A", type="pdf", pages=1, chunks=fewer)
    assert len(await store.chunks("doc_a")) == 1
    assert await store.keyword_search("doc_a", "deposit", 5) == []

    await store.delete_document("doc_a")
    assert await store.document("doc_a") is None
    assert await store.keyword_search("doc_a", "rent", 5) == []


# ---------------------------------------------------------------- indexer + hybrid retrieval


def _stack(
    tmp_path: Path, embedder: FakeEmbedder | None = None
) -> tuple[ChunkStore, DocumentIndexer, HybridRetriever, InMemoryVectorStore, FakeReranker]:
    store = ChunkStore(tmp_path / "chunks.db")
    embedder = embedder or FakeEmbedder()
    vectors = InMemoryVectorStore()
    reranker = FakeReranker()
    indexer = DocumentIndexer(store, embedder, vectors)
    retriever = HybridRetriever(
        store, embedder, vectors, reranker, vector_k=2, keyword_k=2, top_n=2
    )
    return store, indexer, retriever, vectors, reranker


async def test_hybrid_unions_both_searches_then_reranks(tmp_path: Path) -> None:
    _, indexer, retriever, _, reranker = _stack(tmp_path)
    await indexer.index(document_id="doc_a", name="A.pdf", type="pdf", pages=_pages())

    result = await retriever.retrieve(
        document_id="doc_a", document_name="A.pdf", query="security deposit amount"
    )
    assert result.vector_hits == 2 and result.keyword_hits <= 2
    assert result.candidates == len(reranker.calls[0][1])  # every candidate was reranked
    assert len(result.chunks) == 2  # top_n
    best = result.chunks[0]
    assert best.chunk.page == 2
    assert best.rerank_score >= result.chunks[1].rerank_score
    assert best.vector_rank is not None or best.keyword_rank is not None
    assert reranker.calls[0][1][0].startswith("A.pdf · ")  # the reranker sees the header


async def test_purge_removes_chunks_and_vectors(tmp_path: Path) -> None:
    store, indexer, _, vectors, _ = _stack(tmp_path)
    await indexer.index(document_id="doc_a", name="A", type="pdf", pages=_pages())
    assert vectors.points
    await indexer.purge("doc_a")
    assert not vectors.points
    assert await store.document("doc_a") is None


async def test_index_failure_is_a_typed_error_and_stores_nothing(tmp_path: Path) -> None:
    store, indexer, *_ = _stack(tmp_path, FakeEmbedder(fail=True))
    with pytest.raises(RetrievalUnavailableError):
        await indexer.index(document_id="doc_a", name="A", type="pdf", pages=_pages())
    assert await store.document("doc_a") is None


async def test_retrieval_failure_is_a_typed_error(tmp_path: Path) -> None:
    _, indexer, retriever, *_ = _stack(tmp_path)
    await indexer.index(document_id="doc_a", name="A", type="pdf", pages=_pages())
    retriever._embedder = FakeEmbedder(fail=True)
    with pytest.raises(RetrievalUnavailableError) as info:
        await retriever.retrieve(document_id="doc_a", document_name="A", query="rent")
    assert info.value.code == "retrieval_unavailable"


# ---------------------------------------------------------------- eval documents


@pytest.mark.parametrize("name", ["msa", "lease", "nda"])
def test_eval_documents_load_and_chunk(name: str) -> None:
    loaded = load_document(EVAL_DOCS / f"{name}.json")
    chunks = chunk_pages(loaded.id, loaded.pages)
    assert chunks
    assert {c.page for c in chunks} == {p.page for p in loaded.pages}


def test_sentence_split_keeps_closing_quotes_and_every_character() -> None:
    sentence = 'The term "Effective Date." means the signing date. '
    paragraph = " ".join((sentence * 12).split())  # 96 words, must be split
    chunks = chunk_pages("d", [PageText(1, [paragraph])], target_words=30, max_words=40)
    assert len(chunks) > 1
    pieces = [p for c in chunks for p in c.paragraphs]
    assert " ".join(pieces) == paragraph  # nothing dropped, nothing reordered
