"""Plain-text helpers shared by the stand-in adapters."""

import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from legallens.ports.ingestion import PageText

_PAGE_NUMBER = re.compile(r"^(page\s+)?\d{1,4}(\s+of\s+\d{1,4})?$|^-\s*\d{1,4}\s*-$", re.IGNORECASE)
_NUMBERED_HEADING = re.compile(
    r"^((ARTICLE|Article|SECTION|Section|PART|Part)\s+[\dIVXLC]+\b.{0,70}"
    r"|\d+(\.\d+)*\.?\s+[A-Z][^.]{0,60}"
    r"|[IVXLC]+\.\s+[A-Z][^.]{0,60})$"
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])[\"”']?\s+(?=[A-Z\"“(\[])")
_ABBREVIATION = re.compile(
    r"\b(v|vs|No|Nos|Inc|Ltd|Co|Corp|Mr|Mrs|Ms|Dr|St|Cal|App|Civ|Sec|Art|e\.g|i\.e|U\.S|"
    r"para|p|pp|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.$"
)
_WORD = re.compile(r"[a-z0-9$%][a-z0-9$%'-]*")
STOPWORDS = frozenset(
    """a about above after again against all am an and any are as at be because been before
    being below between both but by can could did do does doing down during each few for from
    further had has have having he her here hers him his how i if in into is it its itself just
    me more most my no nor not now of off on once only or other our out over own same she should
    so some such than that the their them then there these they this those through to too under
    until up very was we were what when where which while who whom why will with would you your
    document agreement say says said tell show give please explain what's whats mean""".split()  # noqa: SIM905
)


def is_heading(line: str) -> bool:
    line = line.strip()
    if not line or len(line) > 90:
        return False
    if _NUMBERED_HEADING.match(line):
        return True
    letters = [c for c in line if c.isalpha()]
    return len(letters) >= 3 and line.isupper() and len(line.split()) <= 10


def split_paragraphs(text: str) -> list[str]:
    """Rebuilds paragraphs from PDF text lines: joins wrapped lines, drops page numbers,
    repairs hyphenation and keeps headings on their own."""
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


def sentences(text: str) -> list[str]:
    parts = _SENTENCE_SPLIT.split(text)
    merged: list[str] = []
    for part in parts:
        if merged and _ABBREVIATION.search(merged[-1]):
            merged[-1] = f"{merged[-1]} {part}"
        else:
            merged.append(part)
    return [s.strip() for s in merged if s.strip()]


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    # plain plurals: pays -> pay, days -> day; but not "less", "status", "basis"
    if word.endswith("s") and not word.endswith(("ss", "us", "is")) and len(word) >= 4:
        return word[:-1]
    return word


def terms(text: str) -> set[str]:
    return {
        _stem(w.strip("'-"))
        for w in _WORD.findall(text.lower())
        if w not in STOPWORDS and (len(w) >= 3 or w.isdigit())
    }


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


@dataclass(frozen=True)
class Passage:
    page: int
    section: str | None
    text: str


def passages(pages: Sequence[PageText]) -> list[Passage]:
    """Body paragraphs with the heading in effect for each."""
    out: list[Passage] = []
    section: str | None = None
    for page in pages:
        for paragraph in page.paragraphs:
            if is_heading(paragraph):
                section = truncate(paragraph, 80)
            else:
                out.append(Passage(page.page, section or page.section, paragraph))
    return out


@dataclass(frozen=True)
class Hit:
    score: float
    passage: Passage
    sentence: str


def search(corpus: Sequence[Passage], query: str, *, context: str = "", k: int = 3) -> list[Hit]:
    """Keyword search with IDF weights. Returns hits above a relevance threshold only, so an
    unrelated question gets nothing (and the caller answers "not found")."""
    query_terms = terms(query)
    context_terms = terms(context) - query_terms
    if not query_terms or not corpus:
        return []
    doc_terms = [terms(p.text) for p in corpus]
    df: Counter[str] = Counter(t for ts in doc_terms for t in ts)
    n = len(corpus)

    def idf(term: str) -> float:
        # Words absent from the document weigh like the rarest present word, not more:
        # otherwise filler words in a question ("much", "needed") sink a good match.
        return math.log(1 + n / (1 + max(df[term], 1)))

    total = sum(idf(t) for t in query_terms)
    hits: list[Hit] = []
    for passage, ts in zip(corpus, doc_terms, strict=True):
        matched = query_terms & ts
        if not matched:
            continue
        coverage = sum(idf(t) for t in matched) / total
        bonus = 0.25 * sum(idf(t) for t in context_terms & ts) / max(total, 1e-9)
        enough_terms = len(matched) >= 2 or len(query_terms) == 1
        if coverage >= 0.4 and enough_terms:
            hits.append(Hit(coverage + bonus, passage, best_sentence(passage.text, query_terms)))
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:k]


def best_sentence(text: str, query_terms: Iterable[str]) -> str:
    wanted = set(query_terms)
    candidates = sentences(text) or [text]
    best = max(candidates, key=lambda s: len(terms(s) & wanted))
    return truncate(best, 300)


def matching_sentences(corpus: Sequence[Passage], pattern: re.Pattern[str], k: int) -> list[Hit]:
    """First ``k`` sentences (in reading order) that match ``pattern``."""
    hits: list[Hit] = []
    seen: set[str] = set()
    for passage in corpus:
        for sentence in sentences(passage.text):
            if pattern.search(sentence) and sentence not in seen:
                seen.add(sentence)
                hits.append(Hit(1.0, passage, truncate(sentence, 300)))
                if len(hits) == k:
                    return hits
    return hits
