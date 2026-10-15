"""Reads the JSON page fixtures in ``evals/documents`` (already split into pages).

Real .pdf / .docx files go through ``legallens_ai.ingestion`` (loader or OCR per page), the
same path the app uses.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from legallens_ai.retrieval.chunker import SECTION_CHARS, is_heading
from legallens_ai.schemas import PageText


@dataclass(frozen=True)
class LoadedDocument:
    id: str
    name: str
    type: Literal["pdf", "docx"]
    pages: list[PageText]


def document_id_for(path: Path) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", path.stem.lower()).strip("_") or "document"
    return f"doc_{slug}"[:64]


def _with_sections(pages: list[list[str]]) -> list[PageText]:
    """A page's section: its first heading, or else the last heading before the page."""
    out: list[PageText] = []
    current: str | None = None
    for number, paragraphs in enumerate(pages, start=1):
        headings = [p for p in paragraphs if is_heading(p)]
        section = headings[0][:SECTION_CHARS] if headings else current
        if headings:
            current = headings[-1][:SECTION_CHARS]
        out.append(PageText(page=number, paragraphs=paragraphs, section=section))
    return out


def load_document(path: Path, document_id: str | None = None) -> LoadedDocument:
    suffix = path.suffix.lower()
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        return LoadedDocument(
            id=document_id or data["id"],
            name=data["name"],
            type=data["type"],
            pages=[
                PageText(page=p["page"], paragraphs=p["paragraphs"], section=p.get("section"))
                for p in data["pages"]
            ],
        )
    raise ValueError(
        f"Unsupported file type {suffix!r}: .pdf and .docx go through ingestion "
        "(legallens_ai.ingestion), page fixtures are .json"
    )
