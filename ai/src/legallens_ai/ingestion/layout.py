"""Rebuilds paragraphs from OCR lines (single-column pages; see ingestion.todo.md I8).

OCR gives line boxes, so paragraphs come from geometry, not only from text:

1. Boxes whose vertical extents overlap by at least half a line form one row, read left to
   right (an engine may split a line into several boxes, e.g. "1." and "Premises").
2. Rows are read top to bottom. A new paragraph starts:
   - after a **bigger vertical step**, when the page visibly uses two spacings (line and
     paragraph): a step over ``PARAGRAPH_STEP`` times the page's line pitch;
   - after a row that **ends a sentence and stops short of the right margin** (a paragraph's
     last line). This also works on 1.5- and double-spaced pages, and on pages whose
     paragraphs are all one line, where every step looks the same;
   - at a **heading**: a short row that looks like one (``is_heading``) at the start of a
     paragraph or right after a sentence ends. A full-width ALL-CAPS line is clause text,
     not a heading.
   Steps are measured at each row's left end, so a slightly rotated scan (whose long lines
   have taller boxes) doesn't look like it has paragraph gaps everywhere.
3. Rows of a paragraph are joined, hyphenation is repaired and page numbers are dropped.

Measured on rendered 200 DPI pages (ingestion.todo.md Step 5): line pitch ~1.15x the row
height, paragraph pitch ~1.5x the line pitch.
"""

import re
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from legallens_ai.ingestion.ocr import OcrLine
from legallens_ai.ingestion.text import is_page_number
from legallens_ai.retrieval.chunker import is_heading

ROW_OVERLAP = 0.5
# A page "shows its line spacing" when its tighter steps are at most this many row heights.
LINE_PITCH_MAX = 1.3
# A step of more than this many line pitches starts a new paragraph.
PARAGRAPH_STEP = 1.25
# A row ending at least this share of the text width before the right margin is a last line.
SHORT_LINE = 0.08
# A heading row is at most this share of the text width.
HEADING_WIDTH = 0.6
# OCR often drops the space after a clause number ("1.Term", "4.2.Notice"), which hides the
# heading from ``is_heading``. Only a number followed by a capital letter is touched.
_JOINED_NUMBER = re.compile(r"^(\d+(?:\.\d+)*\.)(?=[A-Z])")
_SENTENCE_END = tuple('.:;!?"”)')


@dataclass
class _Row:
    lines: list[OcrLine]
    top: float
    bottom: float

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def left(self) -> float:
        return min(line.box[0] for line in self.lines)

    @property
    def right(self) -> float:
        return max(line.box[2] for line in self.lines)

    @property
    def y(self) -> float:
        """Where the row starts vertically, at its left end."""
        first = min(self.lines, key=lambda ln: ln.box[0])
        return first.left_y if first.left_y is not None else (first.box[1] + first.box[3]) / 2

    def overlaps(self, line: OcrLine) -> bool:
        shared = min(self.bottom, line.box[3]) - max(self.top, line.box[1])
        return shared >= ROW_OVERLAP * min(self.height, line.height)

    def add(self, line: OcrLine) -> None:
        self.lines.append(line)
        self.top = min(self.top, line.box[1])
        self.bottom = max(self.bottom, line.box[3])

    @property
    def text(self) -> str:
        text = " ".join(line.text for line in sorted(self.lines, key=lambda ln: ln.box[0]))
        return _JOINED_NUMBER.sub(r"\1 ", " ".join(text.split()))


def _rows(lines: Sequence[OcrLine]) -> list[_Row]:
    rows: list[_Row] = []
    for line in sorted(lines, key=lambda ln: (ln.box[1] + ln.box[3]) / 2):
        if line.height <= 0:
            continue
        if rows and rows[-1].overlaps(line):
            rows[-1].add(line)
        else:
            rows.append(_Row([line], line.box[1], line.box[3]))
    return [r for r in rows if not is_page_number(r.text)]


def _line_pitch(rows: list[_Row]) -> float | None:
    """The page's line pitch, when its tighter steps show it; else None (uniform spacing)."""
    steps = sorted(b.y - a.y for a, b in pairwise(rows))
    if len(steps) < 2:
        return None
    tight = steps[len(steps) // 4]
    height = statistics.median(r.height for r in rows)
    return tight if tight <= LINE_PITCH_MAX * height else None


def _join(paragraph: str, text: str) -> str:
    if paragraph.endswith("-") and paragraph[-2:-1].isalpha() and text[:1].islower():
        return paragraph[:-1] + text  # "infor-" + "mation"
    return f"{paragraph} {text}" if paragraph else text


def paragraphs(lines: Sequence[OcrLine]) -> list[str]:
    rows = _rows(lines)
    if not rows:
        return []
    pitch = _line_pitch(rows)
    right = max(r.right for r in rows)
    width = max(right - min(r.left for r in rows), 1.0)

    out: list[str] = []
    current = ""
    for previous, row in zip([None, *rows], rows, strict=False):
        text = row.text
        step_break = (
            previous is not None
            and pitch is not None
            and row.y - previous.y > PARAGRAPH_STEP * pitch
        )
        if step_break and current:
            out.append(current)
            current = ""
        at_start = not current or current.endswith(_SENTENCE_END)
        if at_start and row.right - row.left < HEADING_WIDTH * width and is_heading(text):
            if current:
                out.append(current)
                current = ""
            out.append(text)  # a heading is its own paragraph
            continue
        current = _join(current, text)
        if text.endswith(_SENTENCE_END) and row.right < right - SHORT_LINE * width:
            out.append(current)
            current = ""
    if current:
        out.append(current)
    return out


def page_text(lines: Sequence[OcrLine]) -> str:
    """The rows, top to bottom, one per line (for debugging and tests)."""
    return "\n".join(row.text for row in _rows(lines))


def confidence(lines: Sequence[OcrLine]) -> float | None:
    """Character-weighted mean score: a long misread line counts more than a short one."""
    chars = sum(len(line.text) for line in lines)
    if not chars:
        return None
    return sum(line.score * len(line.text) for line in lines) / chars
