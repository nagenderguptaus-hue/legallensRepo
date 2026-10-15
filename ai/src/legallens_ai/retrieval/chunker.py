"""Paragraph-aware chunking (W21).

Rules, in order of importance:
1. A chunk never crosses a page, so every citation points at exactly one page.
2. Paragraphs are kept whole. Only a paragraph longer than ``max_words`` is split, at sentence
   boundaries (or, for one enormous sentence, at word boundaries).
3. Paragraphs are packed until the chunk reaches ``target_words``.
4. A heading is never left at the end of a chunk: it moves to the next one, with its body.
5. Each chunk's section is the latest heading at or before its first paragraph (falling back
   to the page's section from ingestion).

No overlap between chunks: paragraphs are kept whole and each chunk carries its section in the
search header (``search_text``), so overlap would mostly add duplicate citations.

The heading and sentence patterns mirror the backend's stand-in ingestion (``text.py``), so
sections agree with what ingestion reports for each page.
"""

import re
from collections.abc import Sequence

from legallens_ai.retrieval.types import Chunk
from legallens_ai.schemas import PageText

_NUMBERED_HEADING = re.compile(
    r"^((ARTICLE|Article|SECTION|Section|PART|Part)\s+[\dIVXLC]+\b.{0,70}"
    r"|\d+(\.\d+)*\.?\s+[A-Z][^.]{0,60}"
    r"|[IVXLC]+\.\s+[A-Z][^.]{0,60})$"
)
# Splits after sentence-ending punctuation, keeping a closing quote with its sentence.
_SENTENCE_SPLIT = re.compile(r"(?:(?<=[.!?;])|(?<=[.!?;][\"”']))\s+(?=[A-Z\"“(\[])")
SECTION_CHARS = 80


def is_heading(text: str) -> bool:
    line = text.strip()
    if not line or len(line) > 90:
        return False
    if _NUMBERED_HEADING.match(line):
        return True
    letters = [c for c in line if c.isalpha()]
    return len(letters) >= 3 and line.isupper() and len(line.split()) <= 10


def _words(text: str) -> int:
    return len(text.split())


def _split_long(paragraph: str, max_words: int) -> list[str]:
    """Splits one over-long paragraph into pieces of at most ``max_words`` words."""
    if _words(paragraph) <= max_words:
        return [paragraph]
    pieces: list[str] = []
    current: list[str] = []
    for sentence in _SENTENCE_SPLIT.split(paragraph):
        words = sentence.split()
        while len(words) > max_words:  # a single sentence longer than a chunk
            if current:
                pieces.append(" ".join(current))
                current = []
            pieces.append(" ".join(words[:max_words]))
            words = words[max_words:]
        if current and len(current) + len(words) > max_words:
            pieces.append(" ".join(current))
            current = []
        current.extend(words)
    if current:
        pieces.append(" ".join(current))
    return pieces


def chunk_id(document_id: str, ordinal: int) -> str:
    return f"{document_id}:{ordinal:05d}"


def chunk_pages(
    document_id: str,
    pages: Sequence[PageText],
    *,
    target_words: int = 300,
    max_words: int = 380,
) -> list[Chunk]:
    if target_words > max_words:
        raise ValueError("target_words must not exceed max_words")
    chunks: list[Chunk] = []
    section: str | None = None

    for page in pages:
        if page.section and section is None:
            section = page.section
        units: list[tuple[str, bool]] = []  # (text, is_heading)
        for paragraph in page.paragraphs:
            text = " ".join(paragraph.split())
            if text:
                heading = is_heading(text)
                units.extend((piece, heading) for piece in _split_long(text, max_words))

        current: list[tuple[str, bool]] = []
        current_section = section

        def flush(
            keep: list[tuple[str, bool]], page_number: int, chunk_section: str | None
        ) -> None:
            if keep:
                chunks.append(
                    Chunk(
                        chunk_id=chunk_id(document_id, len(chunks)),
                        document_id=document_id,
                        ordinal=len(chunks),
                        page=page_number,
                        section=chunk_section,
                        paragraphs=tuple(text for text, _ in keep),
                    )
                )

        for text, heading in units:
            size = sum(_words(t) for t, _ in current)
            if current and size + _words(text) > target_words:
                # Rule 4: trailing headings travel with the paragraph that follows them.
                carried: list[tuple[str, bool]] = []
                while current and current[-1][1]:
                    carried.insert(0, current.pop())
                flush(current, page.page, current_section)
                current = carried
                if carried:
                    current_section = carried[0][0][:SECTION_CHARS]
            if not current:
                current_section = text[:SECTION_CHARS] if heading else section
            if heading:
                section = text[:SECTION_CHARS]
            current.append((text, heading))
        flush(current, page.page, current_section)
    return chunks
