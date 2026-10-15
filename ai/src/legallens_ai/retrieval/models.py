"""Local embedding and reranking models (W14, W17), behind small interfaces (NFR-7).

Embedders run on CPU through ``fastembed`` (ONNX, no PyTorch). Rerankers use ``fastembed`` too,
except the Qwen3 rerankers, which are causal LMs scored through ``transformers`` (PyTorch,
installed with ``uv sync --group qwen``). ``make_embedder`` / ``make_reranker`` pick the backend
from the model id, so switching models is a settings change.

Models download once into ``models_dir`` on first use and load lazily, so importing this module
is cheap. Inference runs in a worker thread so the event loop keeps streaming.

Query prefixes matter: most retrieval embedders were trained with an instruction in front of
the *query* (never the passage), and fastembed does not add it. ``QUERY_PREFIXES`` holds each
model's documented prefix; without it a model is measured below its real quality.
"""

import asyncio
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

# fastembed's batch size for passages; small batches keep peak memory low on laptops.
EMBED_BATCH = 16

# The retrieval task, in the words instruction-tuned models (Qwen3) expect.
RETRIEVAL_TASK = (
    "Given a question about a legal document, retrieve the passages of that document that "
    "answer the question"
)
_BGE_QUERY = "Represent this sentence for searching relevant passages: "
QUERY_PREFIXES: dict[str, str] = {
    "BAAI/bge-small-en-v1.5": _BGE_QUERY,
    "BAAI/bge-base-en-v1.5": _BGE_QUERY,
    "BAAI/bge-large-en-v1.5": _BGE_QUERY,
    "mixedbread-ai/mxbai-embed-large-v1": _BGE_QUERY,
    "snowflake/snowflake-arctic-embed-m-long": _BGE_QUERY,
    "snowflake/snowflake-arctic-embed-m": _BGE_QUERY,
    "snowflake/snowflake-arctic-embed-l": _BGE_QUERY,
    "Qwen/Qwen3-Embedding-0.6B": f"Instruct: {RETRIEVAL_TASK}\nQuery:",
    "Qwen/Qwen3-Embedding-0.6B-Q": f"Instruct: {RETRIEVAL_TASK}\nQuery:",
    "nomic-ai/nomic-embed-text-v1.5": "search_query: ",
}
PASSAGE_PREFIXES: dict[str, str] = {"nomic-ai/nomic-embed-text-v1.5": "search_document: "}

# The "not found" gate (W18) per reranker, on that reranker's own score scale: below this best
# score, Ask answers "not found" without calling the LLM. Each value sits under every
# answerable question measured and only stops clearly off-topic ones; borderline questions go
# to the model. Evidence in workflows.todo.md (Phase 3b.1). Uncalibrated rerankers: no gate.
RERANK_MIN_SCORES: dict[str, float] = {
    "Xenova/ms-marco-MiniLM-L-6-v2": -10.5,  # logits
    # logits: answerable ≥ -5.83 (Ask eval paraphrase; LegalBench ≥ 0.58), off-topic -8.78
    "BAAI/bge-reranker-v2-m3": -7.0,
    # P(yes): answerable ≥ 0.909 (LegalBench), unanswerable 0.0001-0.43 (Ask eval)
    "Qwen/Qwen3-Reranker-0.6B": 0.1,
}


class Embedder(Protocol):
    model_name: str

    async def dimension(self) -> int: ...

    async def embed_passages(self, texts: Sequence[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class Reranker(Protocol):
    model_name: str

    async def scores(self, query: str, texts: Sequence[str]) -> list[float]:
        """One relevance score per text, in the same order. Higher is more relevant."""
        ...


class _Lazy:
    """Loads a model once, on first use, from any thread."""

    def __init__(self, load: Any) -> None:
        self._load = load
        self._model: Any = None
        self._lock = threading.Lock()

    def get(self) -> Any:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    self._model = self._load()
        return self._model


class FastEmbedEmbedder:
    def __init__(
        self,
        model_name: str,
        cache_dir: Path,
        *,
        query_prefix: str | None = None,
        passage_prefix: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.query_prefix = (
            QUERY_PREFIXES.get(model_name, "") if query_prefix is None else query_prefix
        )
        self.passage_prefix = (
            PASSAGE_PREFIXES.get(model_name, "") if passage_prefix is None else passage_prefix
        )

        def load() -> Any:
            from fastembed import TextEmbedding

            return TextEmbedding(model_name, cache_dir=str(cache_dir))

        self._model = _Lazy(load)
        self._dimension: int | None = None

    async def dimension(self) -> int:
        if self._dimension is None:
            self._dimension = len(await self.embed_query("dimension probe"))
        return self._dimension

    async def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        def run() -> list[list[float]]:
            model = self._model.get()
            docs = [self.passage_prefix + t for t in texts]
            return [v.tolist() for v in model.passage_embed(docs, batch_size=EMBED_BATCH)]

        return await asyncio.to_thread(run)

    async def embed_query(self, text: str) -> list[float]:
        def run() -> list[float]:
            model = self._model.get()
            return [float(x) for x in next(iter(model.query_embed(self.query_prefix + text)))]

        return await asyncio.to_thread(run)


class FastEmbedReranker:
    def __init__(self, model_name: str, cache_dir: Path) -> None:
        self.model_name = model_name

        def load() -> Any:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            return TextCrossEncoder(model_name, cache_dir=str(cache_dir))

        self._model = _Lazy(load)

    async def scores(self, query: str, texts: Sequence[str]) -> list[float]:
        if not texts:
            return []

        def run() -> list[float]:
            return [float(s) for s in self._model.get().rerank(query, list(texts))]

        return await asyncio.to_thread(run)


# The prompt format from the Qwen3-Reranker model card, verbatim.
_QWEN3_PREFIX = (
    "<|im_start|>system\nJudge whether the Document meets the requirements based on the Query "
    'and the Instruct provided. Note that the answer can only be "yes" or "no".<|im_end|>\n'
    "<|im_start|>user\n"
)
_QWEN3_SUFFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"


class Qwen3Reranker:
    """Qwen3-Reranker: the score is P("yes") that the document answers the query (0 to 1)."""

    def __init__(
        self,
        model_name: str,
        cache_dir: Path,
        *,
        instruction: str = RETRIEVAL_TASK,
        max_length: int = 8192,
        batch_size: int = 4,
    ) -> None:
        self.model_name = model_name
        self.instruction = instruction
        self.max_length = max_length
        self.batch_size = batch_size

        def load() -> tuple[Any, Any, list[int], list[int], int, int]:
            try:
                import torch
                from transformers import AutoModelForCausalLM, AutoTokenizer
            except ImportError as exc:  # pragma: no cover - depends on the install
                raise RuntimeError(
                    f"{model_name} needs PyTorch: run `uv sync --group qwen`."
                ) from exc
            tokenizer: Any = AutoTokenizer.from_pretrained(
                model_name, padding_side="left", cache_dir=str(cache_dir)
            )
            model: Any = AutoModelForCausalLM.from_pretrained(
                model_name, cache_dir=str(cache_dir), dtype=torch.float32
            )
            model.eval()
            prefix = tokenizer.encode(_QWEN3_PREFIX, add_special_tokens=False)
            suffix = tokenizer.encode(_QWEN3_SUFFIX, add_special_tokens=False)
            yes = tokenizer.convert_tokens_to_ids("yes")
            no = tokenizer.convert_tokens_to_ids("no")
            return tokenizer, model, prefix, suffix, yes, no

        self._model = _Lazy(load)

    def _score_batch(self, query: str, docs: Sequence[str]) -> list[float]:
        import torch

        tokenizer, model, prefix, suffix, yes, no = self._model.get()
        pairs = [
            f"<Instruct>: {self.instruction}\n<Query>: {query}\n<Document>: {doc}" for doc in docs
        ]
        inputs = tokenizer(
            pairs,
            padding=False,
            truncation="longest_first",
            return_attention_mask=False,
            max_length=self.max_length - len(prefix) - len(suffix),
        )
        inputs["input_ids"] = [prefix + ids + suffix for ids in inputs["input_ids"]]
        batch = tokenizer.pad(inputs, padding=True, return_tensors="pt", max_length=self.max_length)
        with torch.no_grad():
            logits = model(**batch).logits[:, -1, :]
        pair = torch.stack([logits[:, no], logits[:, yes]], dim=1)
        return [float(p) for p in torch.nn.functional.log_softmax(pair, dim=1)[:, 1].exp()]

    async def scores(self, query: str, texts: Sequence[str]) -> list[float]:
        if not texts:
            return []

        def run() -> list[float]:
            out: list[float] = []
            for start in range(0, len(texts), self.batch_size):
                out.extend(self._score_batch(query, texts[start : start + self.batch_size]))
            return out

        return await asyncio.to_thread(run)


def make_embedder(model_name: str, cache_dir: Path, *, query_prefix: str | None = None) -> Embedder:
    return FastEmbedEmbedder(model_name, cache_dir, query_prefix=query_prefix)


def make_reranker(model_name: str, cache_dir: Path) -> Reranker:
    if model_name.startswith("Qwen/Qwen3-Reranker"):
        return Qwen3Reranker(model_name, cache_dir)
    return FastEmbedReranker(model_name, cache_dir)
