"""All runtime configuration, read from environment variables (prefix ``LL_``) or ``.env``.

Nothing machine-specific lives in code: every deployment difference (paths, host, limits,
which AI adapters to load) is a setting. See ``.env.example`` for the full list.
"""

from functools import cached_property
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LL_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ---- server
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    allow_remote: bool = Field(
        default=False,
        description="Allow binding to a non-loopback host. Only for containers whose port "
        "is published on the host's loopback interface (NFR-5).",
    )
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # ---- storage
    data_dir: Path = Path("data")

    # ---- logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = True

    # ---- limits (NFR-3)
    max_upload_mb: int = Field(default=25, ge=1)
    max_pages: int = Field(default=300, ge=1)
    max_documents: int = Field(default=100, ge=1)
    max_message_chars: int = Field(default=8000, ge=1)
    history_turns: int = Field(default=10, ge=0)

    # ---- ingestion (NFR-8)
    ingestion_timeout_s: float = Field(default=600, gt=0)
    ingestion_max_retries: int = Field(default=2, ge=0)
    ingestion_retry_backoff_s: float = Field(default=1.0, ge=0)

    # ---- chat stream
    stream_first_event_timeout_s: float = Field(default=30, gt=0)
    stream_total_timeout_s: float = Field(default=300, gt=0)
    sse_ping_interval_s: float = Field(default=15, gt=0)

    # ---- AI layer adapters (NFR-7): "standin" or "package.module:factory"
    orchestrator: str = "standin"
    ingestion: str = "standin"

    # ---- stand-in simulations (demo + tests)
    standin_model_offline: bool = False
    standin_token_delay_ms: int = Field(default=20, ge=0)
    standin_fail_midstream: bool = False

    @cached_property
    def resolved_data_dir(self) -> Path:
        return self.data_dir.expanduser().resolve()

    @property
    def db_path(self) -> Path:
        return self.resolved_data_dir / "legallens.db"

    @property
    def uploads_dir(self) -> Path:
        return self.resolved_data_dir / "uploads"

    @property
    def tmp_dir(self) -> Path:
        return self.resolved_data_dir / "tmp"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def is_loopback(self) -> bool:
        return self.host in LOOPBACK_HOSTS
