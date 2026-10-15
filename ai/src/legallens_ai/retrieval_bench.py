"""Retrieval bake-off on LegalBench-RAG: which embedding model and reranker find the right passage.

Setting matches the app: retrieval *within the one document* a question is about. Each document
goes through our real chunker; vector search is exact cosine similarity (as embedded Qdrant is);
keyword search is our SQLite FTS5 BM25. A question's candidates are vector top-K + BM25 top-K,
exactly what the reranker sees in production.

Ground truth is character spans in the source text. A chunk counts as covering a gold span when
they overlap by at least half of the shorter of the two, so a chunk that merely touches the edge
of a span does not count. Metrics, averaged over questions:
- ``recall@k``: share of a question's gold spans covered by the top k chunks;
- ``MRR``: 1 / rank of the first chunk covering any gold span (0 if none is retrieved).

Data: https://github.com/zeroentropy-ai/legalbenchrag (MIT), downloaded into
``data/benchmarks/legalbenchrag`` (git-ignored). Embeddings and reranker scores are cached in
``data/benchmarks/cache``, so re-running only pays for what changed.
"""

import hashlib
import json
import random
import re
import statistics
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from legallens_ai.config import AI_ROOT
from legallens_ai.retrieval.chunk_store import ChunkStore
from legallens_ai.retrieval.chunker import chunk_pages
from legallens_ai.retrieval.indexer import search_text
from legallens_ai.retrieval.loaders import _with_sections
from legallens_ai.retrieval.models import Embedder, Reranker
from legallens_ai.retrieval.types import Chunk

BENCH_ROOT = AI_ROOT / "data" / "benchmarks"
LBR_DIR = BENCH_ROOT / "legalbenchrag"
CACHE_DIR = BENCH_ROOT / "cache"
RESULTS_DIR = BENCH_ROOT / "results"
WORDS_PER_PAGE = 500

# dataset -> (documents, questions per document). Long MAUD merger agreements are the hard case.
DEFAULT_SAMPLE: dict[str, tuple[int, int]] = {
    "contractnli": (8, 4),
    "cuad": (8, 4),
    "maud": (2, 8),
    "privacy_qa": (3, 8),
}


@dataclass(frozen=True)
class SourceParagraph:
    text: str  # whitespace-normalised, as the chunker sees it
    start: int  # character span in the original file
    end: int


@dataclass
class BenchDoc:
    doc_id: str
    dataset: str
    name: str
    chunks: list[Chunk]
    spans: dict[str, tuple[int, int]]  # chunk id -> character span in the original file

    @property
    def words(self) -> int:
        return sum(c.words for c in self.chunks)


@dataclass(frozen=True)
class BenchQuestion:
    id: str
    dataset: str
    doc_id: str
    query: str
    gold: tuple[tuple[int, int], ...]


# ---------------------------------------------------------------- loading


def split_paragraphs(text: str) -> list[SourceParagraph]:
    """Blocks separated by blank lines, with their character spans in ``text``."""
    out: list[SourceParagraph] = []
    position = 0
    for i, part in enumerate(re.split(r"(\n[ \t\r\f\v]*\n\s*)", text)):
        if i % 2 == 0:  # text, not a separator
            norm = " ".join(part.split())
            if norm:
                lead = len(part) - len(part.lstrip())
                out.append(SourceParagraph(norm, position + lead, position + len(part.rstrip())))
        position += len(part)
    return out


def chunk_spans(
    chunks: Sequence[Chunk], paragraphs: Sequence[SourceParagraph]
) -> dict[str, tuple[int, int]]:
    """Maps each chunk back to the original text. Chunk paragraphs are whole source paragraphs
    or word runs of a long one, in order, so a forward-moving cursor finds them."""
    spans: dict[str, tuple[int, int]] = {}
    index, offset = 0, 0
    for chunk in chunks:
        lo, hi = None, None
        for piece in chunk.paragraphs:
            while True:
                found = paragraphs[index].text.find(piece, offset)
                if found >= 0:
                    break
                index, offset = index + 1, 0
            source = paragraphs[index]
            width = source.end - source.start
            length = max(1, len(source.text))
            start = source.start + int(found / length * width)
            end = source.start + int((found + len(piece)) / length * width)
            lo = start if lo is None else min(lo, start)
            hi = end if hi is None else max(hi, end)
            offset = found + len(piece)
        assert lo is not None and hi is not None
        spans[chunk.chunk_id] = (lo, hi)
    return spans


def load_document(dataset: str, file_path: str, doc_id: str) -> BenchDoc:
    text = (LBR_DIR / "corpus" / file_path).read_text(encoding="utf-8", errors="replace")
    paragraphs = split_paragraphs(text)
    pages: list[list[str]] = [[]]
    words = 0
    for p in paragraphs:
        if words >= WORDS_PER_PAGE:
            pages.append([])
            words = 0
        pages[-1].append(p.text)
        words += len(p.text.split())
    chunks = chunk_pages(doc_id, _with_sections(pages))
    return BenchDoc(
        doc_id=doc_id,
        dataset=dataset,
        name=Path(file_path).stem,
        chunks=chunks,
        spans=chunk_spans(chunks, paragraphs),
    )


def load_sample(
    sample: dict[str, tuple[int, int]] | None = None, seed: int = 7
) -> tuple[dict[str, BenchDoc], list[BenchQuestion]]:
    rng = random.Random(seed)  # noqa: S311 (sampling, not security)
    docs: dict[str, BenchDoc] = {}
    questions: list[BenchQuestion] = []
    for dataset, (n_docs, per_doc) in (sample or DEFAULT_SAMPLE).items():
        tests = json.loads((LBR_DIR / "benchmarks" / f"{dataset}.json").read_text(encoding="utf-8"))
        by_file: dict[str, list[dict[str, object]]] = {}
        for test in tests["tests"]:
            files = {s["file_path"] for s in test["snippets"]}
            if len(files) == 1:
                by_file.setdefault(files.pop(), []).append(test)
        eligible = sorted(
            f for f, t in by_file.items() if len(t) >= per_doc and (LBR_DIR / "corpus" / f).exists()
        )
        for number, file_path in enumerate(rng.sample(eligible, min(n_docs, len(eligible)))):
            doc_id = f"{dataset}-{number:02d}"
            docs[doc_id] = load_document(dataset, file_path, doc_id)
            for k, test in enumerate(rng.sample(by_file[file_path], per_doc)):
                snippets = test["snippets"]
                assert isinstance(snippets, list)
                questions.append(
                    BenchQuestion(
                        id=f"{doc_id}-q{k}",
                        dataset=dataset,
                        doc_id=doc_id,
                        query=str(test["query"]),
                        gold=tuple((int(s["span"][0]), int(s["span"][1])) for s in snippets),
                    )
                )
    return docs, questions


# ---------------------------------------------------------------- scoring


def covers(chunk_span: tuple[int, int], gold: tuple[int, int]) -> bool:
    overlap = min(chunk_span[1], gold[1]) - max(chunk_span[0], gold[0])
    shorter = min(chunk_span[1] - chunk_span[0], gold[1] - gold[0])
    return overlap > 0 and overlap >= 0.5 * max(1, shorter)


def recall_at(ranked: Sequence[str], doc: BenchDoc, q: BenchQuestion, k: int) -> float:
    top = [doc.spans[c] for c in ranked[:k]]
    return sum(any(covers(s, g) for s in top) for g in q.gold) / len(q.gold)


def reciprocal_rank(ranked: Sequence[str], doc: BenchDoc, q: BenchQuestion) -> float:
    for rank, cid in enumerate(ranked, start=1):
        if any(covers(doc.spans[cid], g) for g in q.gold):
            return 1.0 / rank
    return 0.0


@dataclass
class Scores:
    values: dict[str, list[float]] = field(default_factory=dict)  # metric -> per question
    by_dataset: dict[str, dict[str, list[float]]] = field(default_factory=dict)

    def add(self, dataset: str, metric: str, value: float) -> None:
        self.values.setdefault(metric, []).append(value)
        self.by_dataset.setdefault(dataset, {}).setdefault(metric, []).append(value)

    def mean(self, metric: str, dataset: str | None = None) -> float:
        values = self.values if dataset is None else self.by_dataset.get(dataset, {})
        return statistics.mean(values.get(metric, [0.0]))


# ---------------------------------------------------------------- caching


def _key(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:16]


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9.-]+", "_", name)


async def embed_documents(
    embedder: Embedder, docs: dict[str, BenchDoc]
) -> tuple[dict[str, np.ndarray], float]:
    """Unit-normalised chunk vectors per document, cached on disk. Returns (vectors, seconds
    spent embedding uncached chunks)."""
    folder = CACHE_DIR / "embeddings" / _safe(embedder.model_name)
    folder.mkdir(parents=True, exist_ok=True)
    out: dict[str, np.ndarray] = {}
    spent = 0.0
    for doc in docs.values():
        texts = [search_text(c, doc.name) for c in doc.chunks]
        path = folder / f"{doc.doc_id}-{_key(*texts)}.npy"
        if path.exists():
            matrix = np.load(path)
        else:
            started = time.perf_counter()
            matrix = np.asarray(await embedder.embed_passages(texts), dtype=np.float32)
            spent += time.perf_counter() - started
            np.save(path, matrix)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        out[doc.doc_id] = matrix / np.maximum(norms, 1e-12)
    return out, spent


async def candidates(
    embedder: Embedder,
    vectors: dict[str, np.ndarray],
    store: ChunkStore,
    docs: dict[str, BenchDoc],
    questions: Sequence[BenchQuestion],
    k: int,
) -> dict[str, tuple[list[str], list[str]]]:
    """Per question: (vector top-k chunk ids, BM25 top-k chunk ids)."""
    out: dict[str, tuple[list[str], list[str]]] = {}
    for q in questions:
        doc = docs[q.doc_id]
        query = np.asarray(await embedder.embed_query(q.query), dtype=np.float32)
        query /= max(float(np.linalg.norm(query)), 1e-12)
        sims = vectors[q.doc_id] @ query
        order = np.argsort(-sims)[:k]
        vector_ids = [doc.chunks[i].chunk_id for i in order]
        keyword_ids = await store.keyword_search(q.doc_id, q.query, k)
        out[q.id] = (vector_ids, keyword_ids)
    return out


async def rerank_scores(
    reranker: Reranker,
    docs: dict[str, BenchDoc],
    questions: Sequence[BenchQuestion],
    pools: dict[str, list[str]],
) -> tuple[dict[str, dict[str, float]], float, int]:
    """Reranker score per (question, candidate chunk), cached. Returns (scores, seconds, pairs
    scored now).

    Cached per (question, chunk text), so scoring another embedder's candidates only pays for
    the chunks not scored before."""
    folder = CACHE_DIR / "rerank" / _safe(reranker.model_name)
    folder.mkdir(parents=True, exist_ok=True)
    out: dict[str, dict[str, float]] = {}
    spent, pairs = 0.0, 0
    for q in questions:
        doc = docs[q.doc_id]
        by_id = {c.chunk_id: c for c in doc.chunks}
        path = folder / f"{q.id}-{_key(q.query)}.json"
        cached: dict[str, float] = (
            json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        )
        texts = {cid: search_text(by_id[cid], doc.name) for cid in pools[q.id]}
        keys = {cid: _key(text) for cid, text in texts.items()}
        missing = [cid for cid in pools[q.id] if keys[cid] not in cached]
        if missing:
            started = time.perf_counter()
            scores = await reranker.scores(q.query, [texts[cid] for cid in missing])
            spent += time.perf_counter() - started
            pairs += len(missing)
            cached.update({keys[cid]: s for cid, s in zip(missing, scores, strict=True)})
            path.write_text(json.dumps(cached), encoding="utf-8")
        out[q.id] = {cid: cached[keys[cid]] for cid in pools[q.id]}
    return out, spent, pairs


# ---------------------------------------------------------------- the bake-off


@dataclass
class EmbedderResult:
    model: str
    scores: Scores
    seconds: float
    chunks_embedded: int
    pools: dict[str, list[str]]  # question id -> vector + BM25 candidates


@dataclass
class RerankerResult:
    model: str
    candidates_from: str
    scores: Scores
    seconds: float
    pairs: int
    best_scores: list[float]


async def open_keyword_index(docs: dict[str, BenchDoc], folder: Path) -> ChunkStore:
    store = ChunkStore(folder / "bench_chunks.db")
    for doc in docs.values():
        pages = max(c.page for c in doc.chunks) if doc.chunks else 0
        await store.replace_document(
            document_id=doc.doc_id, name=doc.name, type="pdf", pages=pages, chunks=doc.chunks
        )
    return store


async def run_embedder(
    embedder: Embedder,
    docs: dict[str, BenchDoc],
    questions: Sequence[BenchQuestion],
    store: ChunkStore,
    k: int = 25,
) -> EmbedderResult:
    vectors, seconds = await embed_documents(embedder, docs)
    found = await candidates(embedder, vectors, store, docs, questions, k)
    scores = Scores()
    pools: dict[str, list[str]] = {}
    for q in questions:
        doc = docs[q.doc_id]
        vector_ids, keyword_ids = found[q.id]
        pool = list(dict.fromkeys([*vector_ids, *keyword_ids]))
        pools[q.id] = pool
        scores.add(q.dataset, "vector_recall@8", recall_at(vector_ids, doc, q, 8))
        scores.add(q.dataset, "vector_recall@25", recall_at(vector_ids, doc, q, 25))
        scores.add(q.dataset, "bm25_recall@25", recall_at(keyword_ids, doc, q, 25))
        scores.add(q.dataset, "pool_recall", recall_at(pool, doc, q, len(pool)))
        scores.add(q.dataset, "vector_mrr", reciprocal_rank(vector_ids, doc, q))
        scores.add(q.dataset, "pool_size", float(len(pool)))
    embedded = sum(len(d.chunks) for d in docs.values()) if seconds else 0
    return EmbedderResult(embedder.model_name, scores, seconds, embedded, pools)


async def run_reranker(
    reranker: Reranker,
    docs: dict[str, BenchDoc],
    questions: Sequence[BenchQuestion],
    pools: dict[str, list[str]],
    candidates_from: str,
) -> RerankerResult:
    all_scores, seconds, pairs = await rerank_scores(reranker, docs, questions, pools)
    scores = Scores()
    best: list[float] = []
    for q in questions:
        doc = docs[q.doc_id]
        by_score = all_scores[q.id]
        ranked = sorted(pools[q.id], key=lambda cid: by_score[cid], reverse=True)
        best.append(by_score[ranked[0]] if ranked else float("nan"))
        scores.add(q.dataset, "recall@3", recall_at(ranked, doc, q, 3))
        scores.add(q.dataset, "recall@8", recall_at(ranked, doc, q, 8))
        scores.add(q.dataset, "mrr", reciprocal_rank(ranked, doc, q))
    return RerankerResult(reranker.model_name, candidates_from, scores, seconds, pairs, best)


def sample_report(docs: dict[str, BenchDoc], questions: Sequence[BenchQuestion]) -> str:
    lines = ["Sample (seeded):"]
    for dataset in DEFAULT_SAMPLE:
        ds = [d for d in docs.values() if d.dataset == dataset]
        if ds:
            qs = sum(1 for q in questions if q.dataset == dataset)
            lines.append(
                f"  {dataset:<12} {len(ds):>2} docs, {qs:>3} questions, "
                f"{sum(d.words for d in ds):>7,} words, {sum(len(d.chunks) for d in ds):>5,} chunks"
            )
    return "\n".join(lines)


def _table(rows: list[tuple[str, Scores]], metrics: list[str], datasets: list[str]) -> list[str]:
    lines = [f"  {'model':<42}" + "".join(f"{m:>18}" for m in metrics)]
    for name, scores in rows:
        lines.append(f"  {name:<42}" + "".join(f"{scores.mean(m):>18.3f}" for m in metrics))
    lines.append("")
    focus = metrics[0]
    lines.append(f"  {focus} by dataset:")
    lines.append(f"  {'model':<42}" + "".join(f"{d:>14}" for d in datasets))
    for name, scores in rows:
        lines.append(f"  {name:<42}" + "".join(f"{scores.mean(focus, d):>14.3f}" for d in datasets))
    return lines


def embedder_report(results: list[EmbedderResult], datasets: list[str]) -> str:
    metrics = ["pool_recall", "vector_recall@25", "vector_recall@8", "vector_mrr", "bm25_recall@25"]
    lines = ["Stage 1: embedding models (candidates = vector top 25 + BM25 top 25)"]
    lines += _table([(r.model, r.scores) for r in results], metrics, datasets)
    lines.append("")
    for r in results:
        speed = f"{r.chunks_embedded / r.seconds:.1f} chunks/s" if r.seconds else "cached"
        lines.append(
            f"  {r.model:<42} pool size {r.scores.mean('pool_size'):.0f} avg; embedding {speed}"
        )
    return "\n".join(lines)


def reranker_report(results: list[RerankerResult], datasets: list[str]) -> str:
    if not results:
        return ""
    lines = [f"Stage 2: rerankers (on candidates from {results[0].candidates_from})"]
    lines += _table(
        [(r.model, r.scores) for r in results], ["recall@8", "recall@3", "mrr"], datasets
    )
    lines.append("")
    for r in results:
        speed = f"{r.pairs / r.seconds:.1f} pairs/s" if r.seconds else "cached"
        lines.append(f"  {r.model:<42} {speed}")
    return "\n".join(lines)


async def bake_off(
    embedders: Sequence[Embedder],
    rerankers: Sequence[Reranker],
    *,
    rerank_on: str | None = None,
    sample: dict[str, tuple[int, int]] | None = None,
    seed: int = 7,
    k: int = 25,
    progress: bool = True,
) -> tuple[str, dict[str, object]]:
    docs, questions = load_sample(sample, seed)
    datasets = [d for d in (sample or DEFAULT_SAMPLE) if any(q.dataset == d for q in questions)]
    report = [sample_report(docs, questions), ""]
    with tempfile.TemporaryDirectory() as tmp:
        store = await open_keyword_index(docs, Path(tmp))
        emb_results: list[EmbedderResult] = []
        for embedder in embedders:
            if progress:
                print(f"… embedding with {embedder.model_name}", flush=True)
            emb_results.append(await run_embedder(embedder, docs, questions, store, k))
        report.append(embedder_report(emb_results, datasets))

        rr_results: list[RerankerResult] = []
        if rerankers:
            if rerank_on == "best":  # the embedder whose candidates cover the most gold spans
                base = max(emb_results, key=lambda r: r.scores.mean("pool_recall"))
            else:
                base = next((r for r in emb_results if r.model == rerank_on), emb_results[0])
            for reranker in rerankers:
                if progress:
                    print(f"… reranking with {reranker.model_name}", flush=True)
                rr_results.append(
                    await run_reranker(reranker, docs, questions, base.pools, base.model)
                )
            report += ["", reranker_report(rr_results, datasets)]

    raw: dict[str, object] = {
        "seed": seed,
        "questions": len(questions),
        "embedders": {r.model: {m: r.scores.mean(m) for m in r.scores.values} for r in emb_results},
        "rerankers": {
            r.model: {
                "candidates_from": r.candidates_from,
                **{m: r.scores.mean(m) for m in r.scores.values},
                **{f"{m}:{d}": r.scores.mean(m, d) for m in r.scores.values for d in datasets},
            }
            for r in rr_results
        },
    }
    return "\n".join(report), raw
