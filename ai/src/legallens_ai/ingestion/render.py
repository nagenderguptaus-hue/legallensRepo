"""Renders PDF pages to grayscale images for OCR (pypdfium2: pip-only, Apache/BSD licensed).

One page is rendered at a time, so a 300-page scan never holds more than one page image in
memory. PDFium is not thread-safe, so every call into it holds one process-wide lock.
"""

import threading
from pathlib import Path
from types import TracebackType
from typing import Any

import numpy as np
import pypdfium2 as pdfium

_PDFIUM = threading.Lock()
# Huge pages (drawings, posters) are scaled down so one page can't exhaust memory.
MAX_PIXELS = 40_000_000


class PdfRenderer:
    def __init__(self, path: Path) -> None:
        with _PDFIUM:
            self._pdf = pdfium.PdfDocument(str(path))

    def __len__(self) -> int:
        with _PDFIUM:
            return len(self._pdf)

    def render(self, index: int, dpi: int) -> np.ndarray[Any, np.dtype[np.uint8]]:
        """The page as an 8-bit grayscale array (height x width), honouring page rotation."""
        with _PDFIUM:
            page = self._pdf[index]
            try:
                width, height = page.get_size()  # PDF points (1/72 inch)
                scale = dpi / 72
                pixels = width * height * scale * scale
                if pixels > MAX_PIXELS:
                    scale *= (MAX_PIXELS / pixels) ** 0.5
                bitmap = page.render(scale=scale, grayscale=True)
                try:
                    return np.array(bitmap.to_numpy(), dtype=np.uint8).squeeze()
                finally:
                    bitmap.close()
            finally:
                page.close()

    def close(self) -> None:
        with _PDFIUM:
            self._pdf.close()

    def __enter__(self) -> "PdfRenderer":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
