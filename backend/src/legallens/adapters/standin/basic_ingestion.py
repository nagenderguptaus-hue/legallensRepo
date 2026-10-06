"""Stand-in ingestion: real text extraction, no OCR, no chunking, no embeddings.

PDF: text per page (pypdf). DOCX: paragraphs and tables in reading order (python-docx), split
into pages at Word's saved page breaks, or every ~500 words when there are none.
"""

import asyncio
import math
from typing import Any

import docx
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader

from legallens.adapters.standin.text import is_heading, split_paragraphs, truncate
from legallens.ports.ingestion import (
    IngestionFailed,
    IngestionInput,
    IngestionResult,
    PageText,
    ProgressReporter,
)

WORDS_PER_PAGE = 500
SCANNED_MESSAGE = (
    "This looks like a scanned document (no text layer). Scanned files need OCR, which "
    "arrives with the AI layer."
)


def _page_list(pages: list[int]) -> str:
    shown = ", ".join(str(p) for p in pages[:10])
    more = f" and {len(pages) - 10} more" if len(pages) > 10 else ""
    return f"page{'s' if len(pages) > 1 else ''} {shown}{more}"


class BasicIngestionPipeline:
    async def run(self, item: IngestionInput, progress: ProgressReporter) -> IngestionResult:
        await progress("validating")
        if item.type == "pdf":
            pages = await self._pdf(item, progress)
        else:
            pages = await self._docx(item, progress)

        await progress("quality_check")
        empty = [p.page for p in pages if not p.paragraphs]
        if len(empty) == len(pages):
            raise IngestionFailed(SCANNED_MESSAGE)
        warnings = []
        if empty:
            warnings.append(
                f"No text layer on {_page_list(empty)}. These pages can't be searched or "
                "cited until OCR is available."
            )
        await progress("chunking")
        await progress("indexing")
        return IngestionResult(pages=pages, is_scanned=bool(empty), warnings=warnings)

    async def purge(self, document_id: str) -> None:
        """Nothing to purge: the stand-in stores no chunks or vectors."""

    # ------------------------------------------------------------ PDF

    async def _pdf(self, item: IngestionInput, progress: ProgressReporter) -> list[PageText]:
        def open_reader() -> PdfReader:
            reader = PdfReader(item.path, strict=False)
            if reader.is_encrypted:
                reader.decrypt("")
            return reader

        try:
            reader = await asyncio.to_thread(open_reader)
        except Exception as exc:
            raise IngestionFailed("This PDF could not be opened. It may be corrupted.") from exc

        total = len(reader.pages)
        sections = _SectionTracker()
        out: list[PageText] = []
        for number, page in enumerate(reader.pages, start=1):
            await progress("extracting", number, total)
            try:
                text = await asyncio.to_thread(page.extract_text)
            except Exception:
                text = ""
            paragraphs = split_paragraphs(text or "")
            section = sections.page([p for p in paragraphs if is_heading(p)])
            out.append(PageText(page=number, paragraphs=paragraphs, section=section))
        return out

    # ------------------------------------------------------------ DOCX

    async def _docx(self, item: IngestionInput, progress: ProgressReporter) -> list[PageText]:
        try:
            blocks = await asyncio.to_thread(_read_docx_blocks, str(item.path))
        except Exception as exc:
            raise IngestionFailed(
                "This Word file could not be opened. It may be corrupted."
            ) from exc

        groups = _paginate(blocks)
        total = len(groups)
        sections = _SectionTracker()
        out: list[PageText] = []
        for number, group in enumerate(groups, start=1):
            await progress("extracting", number, total)
            section = sections.page([text for text, heading, _ in group if heading])
            out.append(
                PageText(page=number, paragraphs=[text for text, _, _ in group], section=section)
            )
        return out


class _SectionTracker:
    """A page's section: its first heading, or else the last heading before the page."""

    def __init__(self) -> None:
        self._current: str | None = None

    def page(self, headings: list[str]) -> str | None:
        section = truncate(headings[0], 80) if headings else self._current
        if headings:
            self._current = truncate(headings[-1], 80)
        return section


# (text, is_heading, starts_new_page)
Block = tuple[str, bool, bool]


def _read_docx_blocks(path: str) -> list[Block]:
    document = docx.Document(path)
    blocks: list[Block] = []
    for part in document.iter_inner_content():
        if isinstance(part, Paragraph):
            text = " ".join(part.text.split())
            new_page = _breaks_page(part)
            if text:
                style = (part.style.name or "") if part.style is not None else ""
                heading = style.startswith(("Heading", "Title")) or is_heading(text)
                blocks.append((text, heading, new_page))
            elif new_page and blocks:
                blocks.append(("", False, True))
        elif isinstance(part, Table):
            for row in part.rows:
                cells = [" ".join(c.text.split()) for c in row.cells]
                # merged cells repeat their text; keep each value once
                unique = list(dict.fromkeys(c for c in cells if c))
                if unique:
                    blocks.append((" | ".join(unique), False, False))
    return blocks


def _breaks_page(paragraph: Paragraph) -> bool:
    if paragraph.contains_page_break or paragraph.paragraph_format.page_break_before:
        return True
    element: Any = paragraph._p
    return bool(element.xpath(".//w:br[@w:type='page']"))


def _paginate(blocks: list[Block]) -> list[list[Block]]:
    if any(new_page for _, _, new_page in blocks[1:]):
        pages: list[list[Block]] = [[]]
        for block in blocks:
            if block[2] and pages[-1]:
                pages.append([])
            if block[0]:
                pages[-1].append(block)
        return [p for p in pages if p] or [[]]

    words_total = sum(len(text.split()) for text, _, _ in blocks)
    if words_total == 0:
        return [[]]
    target = words_total / max(1, math.ceil(words_total / WORDS_PER_PAGE))
    pages = [[]]
    words = 0
    for block in blocks:
        if words >= target and pages[-1]:
            pages.append([])
            words = 0
        pages[-1].append(block)
        words += len(block[0].split())
    return pages
