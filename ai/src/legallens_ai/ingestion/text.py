"""Text clean-up shared by the digital loader and OCR layout.

Ported from the backend stand-in (``backend/src/legallens/adapters/standin/text.py``), so pages
come out the same whichever path produced them. Headings use the chunker's ``is_heading``, so
the sections ingestion reports agree with the sections chunks carry.
"""

import re

from legallens_ai.retrieval.chunker import SECTION_CHARS, is_heading

_PAGE_NUMBER = re.compile(r"^(page\s+)?\d{1,4}(\s+of\s+\d{1,4})?$|^-\s*\d{1,4}\s*-$", re.IGNORECASE)
_LETTER_OR_DIGIT = re.compile(r"[^\W_]")


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def is_page_number(line: str) -> bool:
    """'12', 'Page 3', 'Page 3 of 9', '- 4 -'."""
    return bool(_PAGE_NUMBER.match(line.strip()))


def meaningful_chars(text: str) -> int:
    """Letters and digits only: what decides whether a page has a usable text layer."""
    return len(_LETTER_OR_DIGIT.findall(text))


def split_paragraphs(text: str) -> list[str]:
    """Rebuilds paragraphs from text lines: joins wrapped lines, drops page numbers, repairs
    hyphenation and keeps headings on their own. A blank line always ends a paragraph."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    lines = [line.strip() for line in text.split("\n")]
    longest = max((len(line) for line in lines), default=0)
    paragraphs: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            paragraphs.append(" ".join(current))
            current.clear()

    for line in lines:
        if not line:
            flush()
        elif _PAGE_NUMBER.match(line):
            continue
        elif is_heading(line):
            flush()
            paragraphs.append(line)
        else:
            current.append(line)
            if line[-1] in '.:;!?"”)' and len(line) < 0.85 * longest:
                flush()
    flush()
    return [re.sub(r"\s+", " ", p).strip() for p in paragraphs if p.strip()]


class SectionTracker:
    """A page's section: its first heading, or else the last heading before the page."""

    def __init__(self) -> None:
        self._current: str | None = None

    def page(self, headings: list[str]) -> str | None:
        section = truncate(headings[0], SECTION_CHARS) if headings else self._current
        if headings:
            self._current = truncate(headings[-1], SECTION_CHARS)
        return section
