"""AI layer settings. Each value can come from an ``LL_AI_*`` environment variable or ``.env``."""

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# ai/.env, found the same way whichever folder the command is run from.
AI_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = AI_ROOT / ".env"

Effort = Literal["low", "medium", "high", "xhigh", "max"]


class AISettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LL_AI_", env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    # The standard Anthropic variable, read here so it can also come from .env.
    anthropic_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY", "LL_AI_ANTHROPIC_API_KEY")
    )

    # ------------------------------------------------------------ intent classifier
    intent_model: str = "claude-haiku-4-5"
    intent_temperature: float = Field(default=0.0, ge=0.0, le=1.0)
    intent_max_tokens: int = Field(default=512, ge=64)
    intent_timeout_s: float = Field(default=15.0, gt=0)
    intent_max_retries: int = Field(default=2, ge=0)
    # History sent with each message: the last N turns (user + assistant), each cut to M chars.
    intent_history_turns: int = Field(default=6, ge=0)
    intent_turn_chars: int = Field(default=600, ge=50)

    # ------------------------------------------------------------ query rewriter (Ask)
    rewrite_model: str = "claude-haiku-4-5"
    rewrite_max_tokens: int = Field(default=512, ge=64)
    rewrite_timeout_s: float = Field(default=15.0, gt=0)
    rewrite_history_turns: int = Field(default=6, ge=0)
    rewrite_turn_chars: int = Field(default=600, ge=50)

    # ------------------------------------------------------------ generation
    ask_model: str = "claude-sonnet-5-5"
    ask_effort: Effort = "medium"
    ask_max_tokens: int = Field(default=8000, ge=256)
    ask_timeout_s: float = Field(default=60.0, gt=0)

    # Summary picks its model by document length (W4).
    summary_model: str = "claude-sonnet-5-5"
    summary_long_model: str = "claude-opus-5-5"
    summary_long_threshold_tokens: int = Field(default=60_000, ge=1_000)
    summary_effort: Effort = "medium"
    summary_max_tokens: int = Field(default=16_000, ge=1_000)
    summary_timeout_s: float = Field(default=300.0, gt=0)

    draft_model: str = "claude-opus-5-5"
    draft_effort: Effort = "high"
    draft_max_tokens: int = Field(default=16_000, ge=1_000)
    draft_timeout_s: float = Field(default=300.0, gt=0)
    draft_history_turns: int = Field(default=6, ge=0)
    draft_turn_chars: int = Field(default=1_500, ge=50)

    # Summary and Draft send the whole document; above this they refuse (W29).
    max_document_tokens: int = Field(default=400_000, ge=10_000)
    generation_max_retries: int = Field(default=2, ge=0)
    # Server-side retry on a fallback model if a safety classifier declines (W6).
    refusal_fallbacks: bool = True

    # ------------------------------------------------------------ retrieval
    data_dir: Path = AI_ROOT / "data"
    # Downloaded embedding / reranker models (~4 GB with the defaults), shared by every data_dir.
    models_dir: Path = AI_ROOT / "data" / "models"
    # Unset: Qdrant runs embedded, in <data_dir>/qdrant. Set (e.g. http://localhost:6333): server.
    qdrant_url: str | None = None
    qdrant_api_key: SecretStr | None = None
    qdrant_collection: str = "legallens_chunks"
    # Chosen by the LegalBench-RAG bake-off (workflows.todo.md, Phase 3b.1). Changing the
    # embedding model needs a re-index: the vector store refuses mismatched dimensions.
    embedding_model: str = "BAAI/bge-large-en-v1.5"
    # Text put in front of each search query. Unset: the model's documented prefix
    # (retrieval/models.py QUERY_PREFIXES); "" for none.
    embedding_query_prefix: str | None = None
    # Laptop default: bge-reranker-v2-m3 (ONNX). Where a GPU is available, the bake-off's best,
    # "Qwen/Qwen3-Reranker-0.6B" (needs `uv sync --group qwen`), is a better choice.
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    retrieval_vector_k: int = Field(default=25, ge=1)
    retrieval_keyword_k: int = Field(default=25, ge=1)
    retrieval_top_n: int = Field(default=8, ge=1)
    # Best reranker score below this → "not found" without calling the LLM (W18). Each reranker
    # scores on its own scale, so unset means the calibrated value for the configured reranker
    # (retrieval/models.py RERANK_MIN_SCORES), or no gate for an uncalibrated one.
    rerank_min_score: float | None = None

    # ------------------------------------------------------------ chunking
    chunk_target_words: int = Field(default=300, ge=50)
    # ≈ 500 tokens with the search header: bge-large embeds at most 512 tokens per chunk.
    chunk_max_words: int = Field(default=380, ge=50)

    @property
    def gate_min_score(self) -> float | None:
        """The "not found" threshold in effect: the override, else the reranker's default."""
        if self.rerank_min_score is not None:
            return self.rerank_min_score
        from legallens_ai.retrieval.models import RERANK_MIN_SCORES

        return RERANK_MIN_SCORES.get(self.reranker_model)

    # ------------------------------------------------------------ ingestion (ingestion.todo.md)
    ocr_engine: Literal["rapidocr"] = "rapidocr"
    # "tiny": 2-3 s/page on a laptop CPU, downloads once (a few MB). "small" (bundled in the
    # package) halves the errors on fax-quality scans but takes 7-20 s/page. Bake-off results:
    # ingestion.todo.md §6.
    ocr_model_size: Literal["tiny", "small", "medium"] = "tiny"
    # Pages are rendered at this resolution for OCR.
    ocr_dpi: int = Field(default=200, ge=72, le=600)
    # The engine shrinks images whose longer side exceeds this (pixels).
    ocr_max_side: int = Field(default=2000, ge=500)
    # Per-line 180° rotation classifier: off, it flipped upright lines (ingestion.todo.md).
    ocr_angle_cls: bool = False
    # A PDF page with fewer letters/digits than this in its text layer is OCR'd (I2).
    ocr_min_text_chars: int = Field(default=20, ge=1)
    # OCR'd pages scoring below this get a warning on the document (I9). The scale is
    # model-specific: measured for "tiny" (bad pages <= 0.94, good >= 0.97); "small" needs ~0.98.
    ocr_low_confidence: float = Field(default=0.955, ge=0.0, le=1.0)

    @property
    def qdrant_path(self) -> Path:
        return self.data_dir / "qdrant"

    @property
    def chunk_db_path(self) -> Path:
        return self.data_dir / "chunks.db"
