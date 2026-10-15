"""OCR engines behind one small interface (NFR-7): an image in, text lines with boxes out.

``RapidOcrEngine`` runs PaddleOCR's PP-OCR models on ONNX Runtime (CPU, pip install only). Its
default "small" models ship inside the wheel, so OCR works offline from the first run (NFR-4);
other sizes download once into ``<models_dir>/rapidocr``. Models load lazily on first use and
inference runs in a worker thread, like the embedding models in ``retrieval/models.py``.
"""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

import numpy as np

from legallens_ai.retrieval.models import _Lazy

log = logging.getLogger("legallens_ai.ocr")

Image = np.ndarray[Any, np.dtype[np.uint8]]
RapidModelSize = Literal["tiny", "small", "medium"]


@dataclass(frozen=True)
class OcrLine:
    """One line of text the engine found. Box in pixels: left, top, right, bottom."""

    text: str
    box: tuple[float, float, float, float]
    score: float  # 0 to 1
    # Vertical middle of the line's left edge. On a slightly rotated scan the box of a long
    # line spans more height than the line itself; its left end still sits where it starts.
    left_y: float | None = None

    @property
    def height(self) -> float:
        return self.box[3] - self.box[1]


class OcrEngine(Protocol):
    name: str

    async def read(self, image: Image) -> list[OcrLine]:
        """Text lines in no particular order (layout.py sorts them)."""
        ...


class RapidOcrEngine:
    def __init__(
        self,
        cache_dir: Path,
        *,
        model_size: RapidModelSize = "small",
        max_side: int = 2000,
        angle_cls: bool = False,
    ) -> None:
        self.name = f"rapidocr-ppocrv6-{model_size}"

        def load() -> Any:
            from rapidocr import ModelType, RapidOCR

            params: dict[str, Any] = {
                "Global.log_level": "warning",
                # RapidOCR shrinks larger images to this side length before reading them.
                "Global.max_side_len": max_side,
                # The per-line 180° classifier can flip an upright line and turn it into
                # garbage (seen on a clean 200 DPI page). Pages arrive upright from PDFium.
                "Global.use_cls": angle_cls,
                "Det.model_type": ModelType(model_size),
                "Rec.model_type": ModelType(model_size),
            }
            if model_size != "small":  # not bundled in the wheel: download once, keep locally
                params["Global.model_root_dir"] = str(cache_dir / "rapidocr")
            return RapidOCR(params=params)

        self._model = _Lazy(load)

    async def read(self, image: Image) -> list[OcrLine]:
        def run() -> list[OcrLine]:
            out = self._model.get()(image)
            if out.boxes is None or out.txts is None or out.scores is None:
                return []
            lines: list[OcrLine] = []
            for points, text, score in zip(out.boxes, out.txts, out.scores, strict=True):
                xs = [float(p[0]) for p in points]
                ys = [float(p[1]) for p in points]
                if text.strip():
                    # Corners come clockwise from the top left: the left edge is 0 and 3.
                    left_y = (ys[0] + ys[3]) / 2 if len(ys) == 4 else None
                    box = (min(xs), min(ys), max(xs), max(ys))
                    lines.append(OcrLine(text.strip(), box, float(score), left_y))
            return lines

        return await asyncio.to_thread(run)


def make_ocr_engine(
    engine: str,
    cache_dir: Path,
    *,
    model_size: RapidModelSize = "small",
    max_side: int = 2000,
    angle_cls: bool = False,
) -> OcrEngine:
    if engine == "rapidocr":
        return RapidOcrEngine(
            cache_dir, model_size=model_size, max_side=max_side, angle_cls=angle_cls
        )
    raise ValueError(f"Unknown OCR engine {engine!r}: use 'rapidocr'")
