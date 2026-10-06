"""Stand-in chat orchestrator: keyword rules over the document's real text, no AI model.

It follows the same event protocol and output formats as the real orchestrator will, so
the frontend, persistence and streaming can be built and demoed now:
  - intent from keyword rules (mirrors the frontend mock),
  - Ask: quotes the best-matching passages with citations, or answers "not found",
  - Summary: the fixed six-section template, each section cited or "Not found in document",
  - Draft: memo / case brief skeleton with [CONFIRM: …] and [CITATION NEEDED] placeholders.
Every answer says it is a stand-in, so nobody mistakes it for AI output.
"""

import asyncio
import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import date

from legallens.adapters.standin.text import (
    Hit,
    Passage,
    is_heading,
    matching_sentences,
    passages,
    search,
    truncate,
)
from legallens.config import Settings
from legallens.ports.orchestrator import (
    ChatContext,
    CitationEvent,
    DoneEvent,
    Intent,
    IntentEvent,
    ModelUnavailableError,
    OrchestratorError,
    OrchestratorEvent,
    Outcome,
    RuntimeHealth,
    StatusEvent,
    TokenEvent,
)

MODEL_NAME = "Stand-in (no AI) · rule-based"
CLARIFY_SUGGESTIONS = (
    "Summarize this document",
    "What are the key obligations?",
    "Draft a memo based on this document",
)
STANDIN_NOTE = "_Stand-in reply (no AI model yet): passages are quoted directly from the document._"

_SUMMARY = re.compile(r"\b(summar|overview|tl;?dr|gist|key points|key terms|outline of)")
_DRAFT_VERB = re.compile(r"\b(draft|write|prepare|compose)\b")
_DRAFT_NOUN = re.compile(r"\b(memo|memorandum|case brief|brief me a)\b")
_FOLLOW_UP = re.compile(r"\b(that|this|it|its|those|they|them|these|there|the same|he|she)\b")

_PARTIES = re.compile(
    r"\b(by and between|between|part(y|ies)|plaintiffs?|defendants?|appellants?|appellees?|"
    r"landlord|tenant|lessor|lessee|licensor|licensee|employer|employee|buyer|seller|vendor|"
    r"customer|disclosing|receiving)\b",
    re.IGNORECASE,
)
_DATES = re.compile(
    r"\b((January|February|March|April|May|June|July|August|September|October|November|"
    r"December)\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2}|"
    r"within\s+\w+(\s+\(\d+\))?\s+(business\s+)?days|\d+\s+(calendar\s+|business\s+)?days|"
    r"effective date|term of)\b",
    re.IGNORECASE,
)
_OBLIGATIONS = re.compile(
    r"\b(shall|must|agrees? to|is required to|will pay|obligat\w*|covenants?)\b", re.IGNORECASE
)
_RISKS = re.compile(
    r"\b(terminat\w*|liabilit\w*|indemn\w*|penalt\w*|breach\w*|default\w*|damages|warrant\w*|"
    r"governing law|arbitration|limitation)\b",
    re.IGNORECASE,
)
_PROCEDURE = re.compile(
    r"\b(trial court|appeal\w*|motion|summary judgment|granted|denied|filed|lower court)\b",
    re.IGNORECASE,
)
_ISSUE = re.compile(r"\b(whether|issue|question presented)\b", re.IGNORECASE)
_HOLDING = re.compile(r"\b(we hold|hold that|held that|we conclude|conclude that)\b", re.IGNORECASE)
_DISPOSITION = re.compile(
    r"\b(affirmed|reversed|remanded|dismissed|costs on appeal|judgment is)\b", re.IGNORECASE
)


def detect_intent(message: str) -> Intent:
    m = message.lower().strip()
    if _SUMMARY.search(m):
        return "summary"
    if _DRAFT_VERB.search(m) or _DRAFT_NOUN.search(m):
        return "draft"
    if len(m.split()) <= 2 and not m.endswith("?"):
        return "clarify"
    return "ask"


def is_follow_up(message: str) -> bool:
    return len(message.split()) <= 12 and bool(_FOLLOW_UP.search(message.lower()))


def to_topic(message: str) -> str:
    cleaned = re.sub(
        r"^(please\s+)?(draft|write|prepare|compose)\b\s*(me\s+)?(an?\s+)?",
        "",
        message.strip(),
        flags=re.IGNORECASE,
    )
    cleaned = cleaned[:1].upper() + cleaned[1:]
    return truncate(cleaned, 80) or "Legal memorandum"


def long_date(d: date) -> str:
    return f"{d:%B} {d.day}, {d.year}"


@dataclass
class Reply:
    intent: Intent
    outcome: Outcome
    steps: list[str]
    content: str
    citations: list[CitationEvent] = field(default_factory=list)
    suggestions: Sequence[str] = ()


class _Citer:
    """Numbers citations in the order they are first used."""

    def __init__(self, document_id: str) -> None:
        self.document_id = document_id
        self.items: list[CitationEvent] = []

    def cite(self, hit: Hit) -> str:
        self.items.append(
            CitationEvent(
                index=len(self.items) + 1,
                document_id=self.document_id,
                page=hit.passage.page,
                section=hit.passage.section,
                quote=hit.sentence,
            )
        )
        return f"[{len(self.items)}]"


class RuleBasedOrchestrator:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def health(self) -> RuntimeHealth:
        if self._settings.standin_model_offline:
            return RuntimeHealth(status="unavailable", model=MODEL_NAME)
        return RuntimeHealth(status="ready", model=MODEL_NAME)

    async def stream(self, ctx: ChatContext) -> AsyncIterator[OrchestratorEvent]:
        if self._settings.standin_model_offline:
            raise ModelUnavailableError()
        reply = await self._respond(ctx)
        yield IntentEvent(reply.intent)

        delay = self._settings.standin_token_delay_ms / 1000
        for label in reply.steps:
            yield StatusEvent(label)
            await asyncio.sleep(delay * 10)

        tokens = re.findall(r"\S+\s*", reply.content)
        pairs = ["".join(tokens[i : i + 2]) for i in range(0, len(tokens), 2)]
        for i, token in enumerate(pairs):
            if self._settings.standin_fail_midstream and i == len(pairs) // 2:
                raise OrchestratorError(
                    "stream_interrupted", "The model stopped responding partway through the answer."
                )
            yield TokenEvent(token)
            await asyncio.sleep(delay)

        for citation in reply.citations:
            yield citation
        yield DoneEvent(reply.outcome, tuple(reply.suggestions))

    # ------------------------------------------------------------ responses

    async def _respond(self, ctx: ChatContext) -> Reply:
        intent = detect_intent(ctx.message)
        doc = ctx.document
        doc_name = doc.name if doc else "the document"

        if intent == "clarify":
            content = (
                f"I can help with **{doc_name}** in a few ways. What would you like to do?"
                if doc
                else "I can answer questions about a document, summarize it, or draft a memo "
                "or case brief. What would you like to do?"
            )
            return Reply(
                intent, "clarify", ["Understanding your request"], content, [], CLARIFY_SUGGESTIONS
            )

        if intent in ("ask", "summary") and (doc is None or ctx.pages is None):
            content = (
                "I answer questions **only from your documents**, so I need one to work with. "
                "Upload a PDF or Word file, or pick a Ready document from the library, "
                "then ask again."
                if intent == "ask"
                else "Select or upload a document and I will summarize it section by section, "
                "with citations."
            )
            return Reply(intent, "needs_document", ["Understanding your request"], content)

        corpus = passages(await ctx.pages.all_pages()) if (doc and ctx.pages) else []
        if intent == "summary":
            assert doc is not None
            return self._summary(doc.id, doc_name, doc.pages, corpus)
        if intent == "draft":
            return self._draft(ctx.message, doc.id if doc else None, doc_name, corpus)
        assert doc is not None
        return self._ask(ctx, doc.id, doc_name, corpus)

    def _ask(
        self, ctx: ChatContext, document_id: str, doc_name: str, corpus: list[Passage]
    ) -> Reply:
        previous = next((t.content for t in reversed(ctx.history) if t.role == "user"), "")
        follow_up = bool(previous) and is_follow_up(ctx.message)
        steps = [
            "Understanding your question",
            *(
                [f"Rewriting follow-up with context: “{truncate(previous, 48)}”"]
                if follow_up
                else []
            ),
            f"Searching {doc_name} (keyword)",
            "Picking the best passages",
        ]
        hits = search(corpus, ctx.message, context=previous if follow_up else "", k=3)
        if not hits:
            content = (
                f"I couldn't find this in **{doc_name}**. No passage matched your question "
                "closely enough, so I won't guess."
            )
            return Reply("ask", "not_found", steps, content)

        citer = _Citer(document_id)
        lines = [f"Here is what **{doc_name}** says that matches your question:", ""]
        lines += [f"- “{hit.sentence}” {citer.cite(hit)}" for hit in hits]
        lines += ["", STANDIN_NOTE]
        return Reply("ask", "answered", steps, "\n".join(lines), citer.items)

    def _summary(self, document_id: str, doc_name: str, pages: int, corpus: list[Passage]) -> Reply:
        citer = _Citer(document_id)
        opening = corpus[:1]
        sections: list[tuple[str, list[Hit]]] = [
            ("Document type & purpose", [Hit(1.0, p, truncate(p.text, 300)) for p in opening]),
            ("Parties", matching_sentences(corpus, _PARTIES, 2)),
            ("Key dates & deadlines", matching_sentences(corpus, _DATES, 3)),
            ("Key terms & obligations", matching_sentences(corpus, _OBLIGATIONS, 3)),
            ("Notable risks", matching_sentences(corpus, _RISKS, 3)),
        ]
        parts: list[str] = []
        for heading, hits in sections:
            parts.append(f"### {heading}")
            if hits:
                parts += [f"- {hit.sentence} {citer.cite(hit)}" for hit in hits]
            else:
                parts.append("_Not found in document._")
            parts.append("")
        parts += [
            "### Plain-language overview",
            "_Not available from the stand-in. The AI layer writes this section; the passages "
            "above are quoted directly from the document._",
        ]
        steps = [
            f"Reading {doc_name} section by section",
            f"Scanning {pages} pages",
            "Filling the summary template",
            "Checking coverage and citations",
        ]
        return Reply("summary", "answered", steps, "\n".join(parts), citer.items)

    def _draft(
        self, message: str, document_id: str | None, doc_name: str, corpus: list[Passage]
    ) -> Reply:
        brief = bool(re.search(r"\bbrief\b", message, re.IGNORECASE))
        kind = "case brief" if brief else "memo"
        steps = [
            f"Planning the {kind} outline",
            f"Gathering facts from {doc_name}" if document_id else "No reference document selected",
            "Drafting section by section",
            "Marking facts that need confirmation",
        ]
        citer = _Citer(document_id or "")
        today = long_date(date.today())

        def facts(hits: list[Hit], missing: str) -> list[str]:
            if not document_id or not hits:
                return [f"[CONFIRM: {missing}]"]
            return [f"- {hit.sentence} {citer.cite(hit)}" for hit in hits]

        if brief:
            title = next((p.text for p in corpus[:5] if is_heading(p.text)), None)
            case = truncate(title, 120) if title else "[CONFIRM: case name and citation]"
            lines = [
                "**CASE BRIEF**",
                "",
                f"**Case:** {case}\\",
                "**Prepared by:** [CONFIRM: attorney name]\\",
                f"**Date:** {today}",
                "",
                "### Facts",
                *facts(search(corpus, "facts agreed contract delivered paid", k=2), "key facts"),
                "",
                "### Procedural history",
                *facts(matching_sentences(corpus, _PROCEDURE, 2), "procedural history"),
                "",
                "### Issue",
                *facts(matching_sentences(corpus, _ISSUE, 1), "the issue presented"),
                "",
                "### Holding",
                *facts(matching_sentences(corpus, _HOLDING, 1), "the holding"),
                "",
                "### Reasoning",
                "[CONFIRM: the court's reasoning] [CITATION NEEDED]",
                "",
                "### Disposition",
                *facts(matching_sentences(corpus, _DISPOSITION, 1), "the disposition"),
            ]
        else:
            background = search(corpus, message, k=3) or [
                Hit(1.0, p, truncate(p.text, 300)) for p in corpus[:2]
            ]
            lines = [
                "**MEMORANDUM**",
                "",
                "**To:** [CONFIRM: recipient]\\",
                "**From:** [CONFIRM: attorney name]\\",
                f"**Date:** {today}\\",
                f"**Re:** {to_topic(message)}",
                "",
                "### 1. Question presented",
                "[CONFIRM: the precise question the client needs answered]",
                "",
                "### 2. Short answer",
                "[CONFIRM: short answer once the analysis is complete] [CITATION NEEDED]",
                "",
                "### 3. Background",
                *facts(background, "relevant facts, dates and parties"),
                "",
                "### 4. Analysis",
                "[CONFIRM: governing law and jurisdiction] [CITATION NEEDED]",
                "",
                "### 5. Recommendation",
                "[CONFIRM: recommended course of action]",
            ]
        lines += [
            "",
            "_Stand-in draft (no AI model yet): structure and quoted facts only._"
            if document_id
            else "_Tip: select a Ready document from the library so the draft can quote it "
            "with citations._",
        ]
        return Reply("draft", "answered", steps, "\n".join(lines), citer.items)
