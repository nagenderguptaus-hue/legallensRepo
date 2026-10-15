"""Document ingestion: loader or OCR per page → quality check → chunk → embed → store.

``make_ingestor(settings, retrieval)`` wires it from settings onto an open ``Retrieval``.
"""

from legallens_ai.config import AISettings
from legallens_ai.ingestion.ocr import OcrEngine, OcrLine, make_ocr_engine
from legallens_ai.ingestion.pipeline import DocumentIngestor
from legallens_ai.ingestion.types import (
    IngestionError,
    IngestionOutcome,
    PageReport,
    Progress,
    Stage,
)
from legallens_ai.retrieval import Retrieval


def make_ingestor(
    settings: AISettings, retrieval: Retrieval, *, ocr: OcrEngine | None = None
) -> DocumentIngestor:
    engine = ocr or make_ocr_engine(
        settings.ocr_engine,
        settings.models_dir,
        model_size=settings.ocr_model_size,
        max_side=settings.ocr_max_side,
        angle_cls=settings.ocr_angle_cls,
    )
    return DocumentIngestor(
        retrieval.indexer,
        engine,
        dpi=settings.ocr_dpi,
        min_text_chars=settings.ocr_min_text_chars,
        low_confidence=settings.ocr_low_confidence,
    )


__all__ = [
    "DocumentIngestor",
    "IngestionError",
    "IngestionOutcome",
    "OcrEngine",
    "OcrLine",
    "PageReport",
    "Progress",
    "Stage",
    "make_ingestor",
    "make_ocr_engine",
]
