"""AI-layer ingestion: loader or OCR per page → quality check → chunk → embed → index.

Turn it on with ``uv sync --extra ai`` and ``LL_INGESTION=legallens.adapters.ai_ingestion:create``.
This module only translates between the backend's ingestion port and ``legallens_ai``; the
pipeline itself lives in ``ai/`` (see ``ai/ingestion.todo.md``).

The AI layer's index (chunks DB + embedded Qdrant) goes under ``<LL_DATA_DIR>/ai`` unless
``LL_AI_DATA_DIR`` is set, so one data folder (or Docker volume) holds everything.
"""

from pathlib import Path

from legallens_ai.config import AI_ROOT, AISettings
from legallens_ai.errors import OrchestratorError
from legallens_ai.ingestion import IngestionError, Stage
from legallens_ai.runtime import AIRuntime

from legallens.config import Settings
from legallens.errors import AppError
from legallens.ports.ingestion import (
    IngestionFailed,
    IngestionInput,
    IngestionResult,
    PageText,
    ProgressReporter,
)


def ai_settings_for(settings: Settings) -> AISettings:
    """``AISettings`` (``LL_AI_*`` / ``ai/.env``) with folders that suit the backend."""
    ai = AISettings()
    updates: dict[str, Path] = {}
    if "data_dir" not in ai.model_fields_set:
        updates["data_dir"] = settings.resolved_data_dir / "ai"
    # From a source checkout, models stay shared in ai/data/models. Installed as a package
    # (Docker), the default would point inside the virtualenv: keep them with the data.
    if "models_dir" not in ai.model_fields_set and not (AI_ROOT / "pyproject.toml").is_file():
        updates["models_dir"] = settings.resolved_data_dir / "models"
    return ai.model_copy(update=updates)


class AIIngestionPipeline:
    def __init__(self, runtime: AIRuntime) -> None:
        self.runtime = runtime

    async def run(self, item: IngestionInput, progress: ProgressReporter) -> IngestionResult:
        async def report(stage: Stage, current: int | None, total: int | None) -> None:
            await progress(stage, current, total)

        try:
            ingestor = await self.runtime.ingestor()
            outcome = await ingestor.ingest(
                document_id=item.document_id,
                name=item.name,
                type=item.type,
                path=item.path,
                progress=report,
            )
        except IngestionError as exc:
            raise IngestionFailed(exc.message, retryable=exc.retryable) from exc
        except OrchestratorError as exc:  # e.g. the index can't be opened
            raise IngestionFailed(exc.message, retryable=True) from exc
        return IngestionResult(
            pages=[
                PageText(
                    page=p.page,
                    paragraphs=list(p.paragraphs),
                    section=p.section,
                    ocr=p.ocr,
                    ocr_confidence=p.ocr_confidence,
                )
                for p in outcome.pages
            ],
            is_scanned=outcome.is_scanned,
            warnings=outcome.warnings,
        )

    async def purge(self, document_id: str) -> None:
        try:
            await (await self.runtime.ingestor()).purge(document_id)
        except OrchestratorError as exc:
            raise AppError(503, "index_unavailable", exc.message) from exc

    async def aclose(self) -> None:
        await self.runtime.close()


def create(settings: Settings) -> AIIngestionPipeline:
    """The ingestion half of the process's shared AI stack (``adapters/ai.py``): with AI chat
    on, chat and ingestion must use one runtime, since embedded Qdrant locks its folder."""
    from legallens.adapters.ai import stack_for  # ai.py imports this module

    return stack_for(settings).ingestion
