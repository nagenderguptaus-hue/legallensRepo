"""The ingestion pipeline: route each page → loader or OCR → quality check → chunk → embed → store.

PDF pages are routed one by one (I1). A page whose text layer has at least ``min_text_chars``
letters/digits is read by the loader; any other page is rendered and OCR'd. Word files always
go through the loader (I3). Chunking, embedding and storage are ``DocumentIndexer``'s job, the
same for every route, so an OCR'd page is searched and cited like a digital one.

Errors are ``IngestionError`` with a message for the document card and a ``retryable`` flag
for the backend's job runner (I11). Logs carry ids, counts, scores and timings, never text.
"""

import asyncio
import logging
import time
from pathlib import Path
from typing import Literal

from legallens_ai.errors import RetrievalUnavailableError
from legallens_ai.ingestion import layout
from legallens_ai.ingestion.digital import open_pdf, pdf_page_text, read_docx_pages
from legallens_ai.ingestion.ocr import Image, OcrEngine, OcrLine
from legallens_ai.ingestion.render import PdfRenderer
from legallens_ai.ingestion.text import SectionTracker, meaningful_chars, split_paragraphs
from legallens_ai.ingestion.types import (
    IngestionError,
    IngestionOutcome,
    PageReport,
    Progress,
    Route,
    Stage,
)
from legallens_ai.retrieval.chunker import is_heading
from legallens_ai.retrieval.indexer import DocumentIndexer
from legallens_ai.schemas import PageText

log = logging.getLogger("legallens_ai.ingestion")

UNREADABLE_PDF = "This PDF could not be opened. It may be corrupted."
UNREADABLE_DOCX = "This Word file could not be opened. It may be corrupted."
NO_TEXT_PDF = (
    "No text could be found in this document, even with OCR. Check that the scan is readable "
    "and upload it again."
)
NO_TEXT_DOCX = "This Word file contains no text."
OCR_UNAVAILABLE = "OCR is not available on this server, so scanned pages can't be read."
INDEX_UNAVAILABLE = "The document could not be indexed. Retry in a moment."


async def _no_progress(stage: Stage, current: int | None, total: int | None) -> None:
    return None


def page_list(pages: list[int]) -> str:
    shown = ", ".join(str(p) for p in pages[:10])
    more = f" and {len(pages) - 10} more" if len(pages) > 10 else ""
    return f"page{'s' if len(pages) > 1 else ''} {shown}{more}"


def _words(paragraphs: list[str]) -> int:
    return sum(len(p.split()) for p in paragraphs)


class DocumentIngestor:
    def __init__(
        self,
        indexer: DocumentIndexer,
        ocr: OcrEngine,
        *,
        dpi: int = 200,
        min_text_chars: int = 20,
        low_confidence: float = 0.955,
    ) -> None:
        self._indexer = indexer
        self._ocr = ocr
        self.dpi = dpi
        self.min_text_chars = min_text_chars
        self.low_confidence = low_confidence

    async def ingest(
        self,
        *,
        document_id: str,
        name: str,
        type: Literal["pdf", "docx"],
        path: Path,
        progress: Progress | None = None,
    ) -> IngestionOutcome:
        report = progress or _no_progress
        started = time.perf_counter()
        await report("validating", None, None)
        if type == "pdf":
            pages, reports = await self._pdf(path, report)
        else:
            pages, reports = await self._docx(path, report)

        await report("quality_check", None, None)
        warnings = self._quality(pages, reports, type)
        try:
            document = await self._indexer.index(
                document_id=document_id, name=name, type=type, pages=pages, progress=report
            )
        except RetrievalUnavailableError as exc:
            raise IngestionError("index_unavailable", INDEX_UNAVAILABLE, retryable=True) from exc

        ocr_pages = [r for r in reports if r.route == "ocr"]
        log.info(
            "document_ingested document_id=%s type=%s pages=%d ocr_pages=%d chunks=%d "
            "warnings=%d ocr_ms=%.0f total_ms=%.0f",
            document_id,
            type,
            len(pages),
            len(ocr_pages),
            document.chunks,
            len(warnings),
            sum(r.ms for r in ocr_pages),
            (time.perf_counter() - started) * 1000,
        )
        return IngestionOutcome(
            pages=pages,
            is_scanned=bool(ocr_pages),
            warnings=warnings,
            document=document,
            reports=reports,
        )

    async def purge(self, document_id: str) -> None:
        """Deletes the document's chunks and vectors. Safe for unknown documents (FR-5)."""
        try:
            await self._indexer.purge(document_id)
        except RetrievalUnavailableError as exc:
            raise IngestionError("index_unavailable", exc.message, retryable=True) from exc

    # ------------------------------------------------------------ PDF

    async def _pdf(self, path: Path, report: Progress) -> tuple[list[PageText], list[PageReport]]:
        try:
            reader = await asyncio.to_thread(open_pdf, path)
            total = len(reader.pages)
        except Exception as exc:
            raise IngestionError("unreadable_file", UNREADABLE_PDF) from exc

        pages: list[PageText] = []
        reports: list[PageReport] = []
        sections = SectionTracker()
        renderer: PdfRenderer | None = None  # opened at the first page without a text layer
        try:
            for index in range(total):
                number = index + 1
                started = time.perf_counter()
                text = await asyncio.to_thread(pdf_page_text, reader, index)
                route: Route
                score: float | None = None
                if meaningful_chars(text) >= self.min_text_chars:
                    route = "digital"
                    await report("extracting", number, total)
                    paragraphs = split_paragraphs(text)
                else:
                    route = "ocr"
                    await report("ocr", number, total)
                    if renderer is None:
                        renderer = await self._open_renderer(path)
                    lines = await self._ocr_page(renderer, index, number)
                    paragraphs = layout.paragraphs(lines)
                    raw = layout.confidence(lines) if paragraphs else None
                    score = round(raw, 3) if raw is not None else None
                section = sections.page([p for p in paragraphs if is_heading(p)])
                pages.append(
                    PageText(
                        page=number,
                        paragraphs=paragraphs,
                        section=section,
                        ocr=route == "ocr",
                        ocr_confidence=score,
                    )
                )
                reports.append(
                    PageReport(
                        page=number,
                        route=route,
                        paragraphs=len(paragraphs),
                        words=_words(paragraphs),
                        ocr_confidence=score,
                        ms=(time.perf_counter() - started) * 1000,
                    )
                )
        finally:
            if renderer is not None:
                await asyncio.to_thread(renderer.close)
        return pages, reports

    async def _open_renderer(self, path: Path) -> PdfRenderer:
        try:
            return await asyncio.to_thread(PdfRenderer, path)
        except Exception as exc:
            raise IngestionError("unreadable_file", UNREADABLE_PDF) from exc

    async def _ocr_page(self, renderer: PdfRenderer, index: int, number: int) -> list[OcrLine]:
        try:
            image: Image = await asyncio.to_thread(renderer.render, index, self.dpi)
        except Exception as exc:
            # One damaged page shouldn't sink the document: it is reported as blank.
            log.warning("render_failed page=%d error=%s", number, type(exc).__name__)
            return []
        try:
            return await self._ocr.read(image)
        except (ImportError, OSError) as exc:  # engine not installed / model files missing
            log.warning("ocr_unavailable engine=%s error=%s", self._ocr.name, type(exc).__name__)
            raise IngestionError("ocr_unavailable", OCR_UNAVAILABLE) from exc
        except Exception as exc:
            log.warning("ocr_failed page=%d error=%s", number, type(exc).__name__)
            raise IngestionError(
                "ocr_failed", f"OCR failed on page {number}. Retry in a moment.", retryable=True
            ) from exc

    # ------------------------------------------------------------ DOCX

    async def _docx(self, path: Path, report: Progress) -> tuple[list[PageText], list[PageReport]]:
        try:
            docx_pages = await asyncio.to_thread(read_docx_pages, path)
        except Exception as exc:
            raise IngestionError("unreadable_file", UNREADABLE_DOCX) from exc
        pages: list[PageText] = []
        reports: list[PageReport] = []
        sections = SectionTracker()
        for number, page in enumerate(docx_pages, start=1):
            await report("extracting", number, len(docx_pages))
            pages.append(
                PageText(
                    page=number, paragraphs=page.paragraphs, section=sections.page(page.headings)
                )
            )
            reports.append(
                PageReport(
                    number, "digital", len(page.paragraphs), _words(page.paragraphs), None, 0
                )
            )
        return pages, reports

    # ------------------------------------------------------------ quality check

    def _quality(
        self, pages: list[PageText], reports: list[PageReport], type: Literal["pdf", "docx"]
    ) -> list[str]:
        if not any(page.paragraphs for page in pages):
            raise IngestionError("no_text", NO_TEXT_PDF if type == "pdf" else NO_TEXT_DOCX)
        warnings: list[str] = []
        blank = [r.page for r in reports if r.route == "ocr" and not r.paragraphs]
        if blank:
            warnings.append(
                f"No text found on {page_list(blank)} (blank or unreadable). These pages can't "
                "be searched or cited."
            )
        low = [
            r.page
            for r in reports
            if r.ocr_confidence is not None and r.ocr_confidence < self.low_confidence
        ]
        if low:
            warnings.append(
                f"Low OCR confidence on {page_list(low)}. Check quotes from these pages against "
                "the original."
            )
        return warnings
