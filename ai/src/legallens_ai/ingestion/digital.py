"""The loader: text from files that carry it (digital PDF pages, Word files).

Ported from the backend stand-in (``basic_ingestion.py``), which is tested against real files.
PDF: the text layer of one page at a time (pypdf). DOCX: paragraphs and table rows in reading
order (python-docx), split into pages at Word's saved page breaks, or every ~500 words when
there are none. Blocking functions: call them through ``asyncio.to_thread``.
"""

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import docx
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader

from legallens_ai.retrieval.chunker import is_heading

DOCX_WORDS_PER_PAGE = 500


# ------------------------------------------------------------ PDF


def open_pdf(path: Path) -> PdfReader:
    reader = PdfReader(path, strict=False)
    if reader.is_encrypted:
        reader.decrypt("")  # an owner password only; real passwords are refused at upload
    return reader


def pdf_page_text(reader: PdfReader, index: int) -> str:
    """The page's text layer, or "" when it has none or it can't be read."""
    try:
        return reader.pages[index].extract_text() or ""
    except Exception:
        return ""


# ------------------------------------------------------------ DOCX


@dataclass(frozen=True)
class DocxPage:
    paragraphs: list[str]
    headings: list[str]  # paragraphs in a Heading/Title style, or that look like headings


# (text, is_heading, starts_new_page)
_Block = tuple[str, bool, bool]


def read_docx_pages(path: Path) -> list[DocxPage]:
    groups = _paginate(_read_blocks(path))
    return [
        DocxPage(
            paragraphs=[text for text, _, _ in group],
            headings=[text for text, heading, _ in group if heading],
        )
        for group in groups
    ]


def _read_blocks(path: Path) -> list[_Block]:
    document = docx.Document(str(path))
    blocks: list[_Block] = []
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


def _paginate(blocks: list[_Block]) -> list[list[_Block]]:
    if any(new_page for _, _, new_page in blocks[1:]):
        pages: list[list[_Block]] = [[]]
        for block in blocks:
            if block[2] and pages[-1]:
                pages.append([])
            if block[0]:
                pages[-1].append(block)
        return [p for p in pages if p] or [[]]

    words_total = sum(len(text.split()) for text, _, _ in blocks)
    if words_total == 0:
        return [[]]
    target = words_total / max(1, math.ceil(words_total / DOCX_WORDS_PER_PAGE))
    pages = [[]]
    words = 0
    for block in blocks:
        if words >= target and pages[-1]:
            pages.append([])
            words = 0
        pages[-1].append(block)
        words += len(block[0].split())
    return pages
