"""Checks run on a finished answer (W24, W30, W37). Deterministic, no model calls.

They report problems rather than edit the text, because the text has already streamed to the
lawyer. Each workflow logs the findings as warnings, and the evals count them.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

NOT_FOUND = "I couldn't find this in the document."
_MARKER = re.compile(r"\s*\[\d+\]")
_NOT_FOUND_START = re.compile(r"^\W*i couldn['’]t find this in the document", re.IGNORECASE)


def strip_markers(text: str) -> str:
    return _MARKER.sub("", text)


def is_not_found(text: str) -> bool:
    """The model gave the fixed "not found" reply (possibly with a marker or punctuation)."""
    return bool(_NOT_FOUND_START.match(strip_markers(text).strip()))


# ---------------------------------------------------------------- summary (FR-12, FR-13)

SUMMARY_SECTIONS: tuple[str, ...] = (
    "Document type & purpose",
    "Parties",
    "Key dates & deadlines",
    "Key terms / obligations / holdings",
    "Notable risks",
    "Plain-language overview",
)
_HEADING = re.compile(r"^#{1,4}\s*(.+?)\s*$", re.MULTILINE)
SECTION_NOT_FOUND = "not found in document"


def _norm_heading(text: str) -> str:
    return re.sub(r"[^a-z]+", " ", text.lower().replace("&", " and ")).strip()


@dataclass(frozen=True)
class SectionCheck:
    heading: str
    present: bool
    not_found: bool
    citations: int

    @property
    def ok(self) -> bool:
        return self.present and (self.not_found or self.citations > 0)


def check_summary(text: str) -> list[SectionCheck]:
    """One result per required section: present? marked "Not found"? how many [n] markers?"""
    headings = list(_HEADING.finditer(text))
    bodies: dict[str, str] = {}
    for i, match in enumerate(headings):
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        bodies[_norm_heading(match.group(1))] = text[match.end() : end]
    results = []
    for section in SUMMARY_SECTIONS:
        body = bodies.get(_norm_heading(section))
        if body is None:
            results.append(SectionCheck(section, False, False, 0))
            continue
        results.append(
            SectionCheck(
                section,
                True,
                SECTION_NOT_FOUND in body.lower(),
                len(_MARKER.findall(body)),
            )
        )
    return results


# ---------------------------------------------------------------- draft (FR-17)

PLACEHOLDER = re.compile(r"\[(?:CITATION NEEDED|CONFIRM)\b[^\]]*\]")
_NAME = r"[A-Z][\w.&'’-]*"
_REPORTERS = (
    r"U\.\s?S\.|S\.\s?Ct\.|L\.\s?Ed\.(?:\s?2d)?|F\.(?:\s?(?:2d|3d|4th))?|F\.\s?Supp\.(?:\s?(?:2d|3d))?"
    r"|F\.\s?App(?:'|’)x|B\.R\.|Cal\.(?:\s?App\.)?(?:\s?(?:2d|3d|4th|5th))?"
    r"|Cal\.\s?Rptr\.(?:\s?(?:2d|3d))?|N\.Y\.(?:\s?(?:2d|3d))?|N\.Y\.S\.(?:\s?(?:2d|3d))?"
    r"|N\.E\.(?:\s?(?:2d|3d))?|N\.W\.(?:\s?2d)?|S\.E\.(?:\s?2d)?|S\.W\.(?:\s?(?:2d|3d))?"
    r"|So\.(?:\s?(?:2d|3d))?|A\.(?:\s?(?:2d|3d))?|P\.(?:\s?(?:2d|3d))?"
)
LEGAL_CITATION = re.compile(
    # Case names: "Smith v. Jones", "In re Marriage of Brown" is not matched on purpose (too
    # broad); reporter cites below catch the citation itself.
    rf"\b{_NAME}(?:\s+{_NAME}){{0,4}}\s+v\.\s+{_NAME}(?:\s+{_NAME}){{0,4}}"
    # Reporter citations: "550 U.S. 544", "123 F.3d 456", "45 Cal. App. 4th 123".
    rf"|\b\d{{1,4}}\s+(?:{_REPORTERS})\s+\d{{1,5}}"
    # Federal statutes and regulations: "42 U.S.C. § 1983", "29 C.F.R. § 1604.11".
    r"|\b\d{1,3}\s+(?:U\.S\.C\.|C\.F\.R\.)\s*(?:§+\s*)?[\d.]+[\w.()-]*"
    # Named codes with a section: "Cal. Civ. Code § 1671", "Civil Code section 1951.2".
    r"|\b(?:Cal\.|California|N\.Y\.|Tex\.|Fla\.)?\s*(?:Civ(?:il|\.)|Bus\.|Lab(?:or|\.)|Penal|Gov(?:ernment|\.)"
    r"|Prob(?:ate|\.))\s*(?:&\s*Prof\.\s*)?Code\s*(?:§+|section|sec\.)\s*\d+[\w.()-]*"
)


# Citation signals a case-name match may swallow: "See Smith v. Jones" → "Smith v. Jones".
_SIGNAL = re.compile(r"^(?:(?:See|See also|Cf\.|Compare|But|Accord|In|E\.g\.,?)\s+)+")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


@dataclass(frozen=True)
class DraftCheck:
    placeholders: int
    invented_citations: tuple[str, ...]


def check_draft(text: str, sources: Iterable[str]) -> DraftCheck:
    """Counts placeholders, and lists legal citations that appear in none of the sources."""
    body = PLACEHOLDER.sub(" ", text)  # authorities named inside a placeholder are fine
    haystack = _norm(" \n ".join(sources))
    invented = []
    for match in LEGAL_CITATION.finditer(body):
        found = _SIGNAL.sub("", match.group(0).strip()).rstrip(".,;:")
        if _norm(found) not in haystack and found not in invented:
            invented.append(found)
    return DraftCheck(
        placeholders=len(PLACEHOLDER.findall(text)), invented_citations=tuple(invented)
    )
