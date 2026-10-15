"""Evals for the query rewriter and the Ask workflow, against real models.

Rewrite cases (``evals/rewrite_cases.jsonl``) check the relation (standalone / follow_up) and,
for follow-ups, that the rewritten query keeps the terms it must and adds none it must not.

Ask cases (``evals/ask_cases.jsonl``) run the whole workflow over the synthetic documents in
``evals/documents`` and score what the BRD (§6) asks for: correct outcome (answered /
not found), a citation on the expected page, the key facts in the answer, and no uncited
answers. Retrieval recall (was the expected page in the top N at all?) is reported separately,
so a miss can be traced to retrieval or to generation.

``must_include`` is a list of groups: every group must match, and a group matches when any of
its alternatives appears in the text (case-insensitive).
"""

import asyncio
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from legallens_ai.config import AI_ROOT
from legallens_ai.errors import OrchestratorError
from legallens_ai.query_rewriter import QueryRewriter, RewriteResult
from legallens_ai.retrieval import Retrieval
from legallens_ai.retrieval.loaders import load_document
from legallens_ai.schemas import DocumentInfo, Intent, OrchestratorRequest, Outcome, Turn
from legallens_ai.workflows.ask import AskTrace, AskWorkflow
from legallens_ai.workflows.checks import strip_markers

EVALS = AI_ROOT / "evals"
REWRITE_CASES = EVALS / "rewrite_cases.jsonl"
ASK_CASES = EVALS / "ask_cases.jsonl"
DOCUMENTS = EVALS / "documents"

# List prices, USD per million tokens (cost estimate only).
PRICES = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}


def estimate_cost(model: str | None, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = PRICES.get(model or "", (0.0, 0.0))
    return input_tokens / 1e6 * price_in + output_tokens / 1e6 * price_out


def matches(text: str, groups: list[list[str]]) -> bool:
    low = text.lower()
    return all(any(alt.lower() in low for alt in group) for group in groups)


def contains_any(text: str, phrases: list[str]) -> list[str]:
    low = text.lower()
    return [p for p in phrases if p.lower() in low]


class CaseTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str
    intent: Intent | None = None


def _turns(history: list[CaseTurn]) -> list[Turn]:
    return [Turn(role=t.role, content=t.content, intent=t.intent) for t in history]


def _load[T: BaseModel](path: Path, model: type[T]) -> list[T]:
    cases: list[T] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                cases.append(model.model_validate_json(line))
            except ValueError as exc:
                raise ValueError(f"{path.name}:{number}: {exc}") from exc
    ids = Counter(getattr(c, "id") for c in cases)  # noqa: B009 (generic T)
    if dupes := [i for i, n in ids.items() if n > 1]:
        raise ValueError(f"Duplicate case ids in {path.name}: {dupes}")
    return cases


def _percentile(values: list[float], q: float) -> float:
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * q))]


# ================================================================ rewrite


class RewriteCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    question: str
    history: list[CaseTurn] = []
    expected: Literal["standalone", "follow_up"]
    must_include: list[list[str]] = []
    must_not_include: list[str] = []
    note: str | None = None


@dataclass
class RewriteCaseResult:
    case: RewriteCase
    result: RewriteResult | None
    error: str | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def correct(self) -> bool:
        return self.error is None and not self.problems


def load_rewrite_cases(path: Path = REWRITE_CASES) -> list[RewriteCase]:
    return _load(path, RewriteCase)


def score_rewrite(case: RewriteCase, result: RewriteResult) -> list[str]:
    problems = []
    relation = "follow_up" if result.rewritten else "standalone"
    if relation != case.expected:
        problems.append(f"relation {relation}, expected {case.expected}")
    if case.expected == "standalone" and result.query != case.question.strip():
        problems.append("standalone question was changed")
    if case.must_include and not matches(result.query, case.must_include):
        problems.append(f"missing terms {case.must_include}")
    if bad := contains_any(result.query, case.must_not_include):
        problems.append(f"contains {bad}")
    return problems


async def run_rewrite_cases(
    rewriter: QueryRewriter, cases: list[RewriteCase], concurrency: int = 4
) -> list[RewriteCaseResult]:
    gate = asyncio.Semaphore(concurrency)

    async def one(case: RewriteCase) -> RewriteCaseResult:
        async with gate:
            try:
                result = await rewriter.rewrite(case.question, _turns(case.history))
            except OrchestratorError as exc:
                return RewriteCaseResult(case, None, exc.code)
            return RewriteCaseResult(case, result, problems=score_rewrite(case, result))

    return list(await asyncio.gather(*(one(c) for c in cases)))


def rewrite_report(results: list[RewriteCaseResult]) -> str:
    total = len(results)
    correct = sum(r.correct for r in results)
    lines = [f"Rewrite accuracy: {correct}/{total} ({correct / total:.0%})"]
    for expected in ("standalone", "follow_up"):
        rows = [r for r in results if r.case.expected == expected]
        if rows:
            lines.append(f"  {expected:<11} {sum(r.correct for r in rows)}/{len(rows)}")
    skipped = sum(1 for r in results if r.result and r.result.reason == "no_history")
    lines.append(f"  no model call (empty history): {skipped}")
    lines.append("")
    for r in results:
        mark = "ok  " if r.correct else "MISS"
        query = r.result.query if r.result else f"error ({r.error})"
        lines.append(f"{mark} [{r.case.id}] {r.case.question}")
        if r.result and r.result.rewritten:
            lines.append(f"       → {query}")
        if not r.correct:
            lines += [f"       ! {p}" for p in r.problems]
            if r.result and r.result.rationale:
                lines.append(f"       rationale: {r.result.rationale}")
    called = [r.result for r in results if r.result and r.result.model]
    if called:
        tokens_in = sum(x.usage.input_tokens for x in called)
        tokens_out = sum(x.usage.output_tokens for x in called)
        cost = estimate_cost(called[0].model, tokens_in, tokens_out)
        lines += [
            "",
            f"Latency: p50 {_percentile([x.latency_ms for x in called], 0.5):.0f} ms",
            f"Tokens: {tokens_in:,} in, {tokens_out:,} out (~${cost:.4f})",
        ]
    return "\n".join(lines)


# ================================================================ ask


class AskCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    document: str  # a file stem in evals/documents
    question: str
    history: list[CaseTurn] = []
    expected: Literal["answered", "not_found"]
    pages: list[int] = []
    must_include: list[list[str]] = []
    must_not_include: list[str] = []
    note: str | None = None


@dataclass
class AskCaseResult:
    case: AskCase
    trace: AskTrace
    error: str | None = None

    @property
    def outcome(self) -> Outcome | None:
        return self.trace.outcome

    @property
    def text(self) -> str:
        return self.trace.generation.text if self.trace.generation else ""

    @property
    def outcome_ok(self) -> bool:
        return self.error is None and self.outcome == self.case.expected

    @property
    def cited_pages(self) -> set[int]:
        g = self.trace.generation
        return {c.page for c in g.citations} if g else set()

    @property
    def citation_ok(self) -> bool:
        return bool(self.cited_pages & set(self.case.pages))

    @property
    def content_ok(self) -> bool:
        plain = strip_markers(self.text)
        return matches(plain, self.case.must_include) and not contains_any(
            plain, self.case.must_not_include
        )

    @property
    def retrieved(self) -> bool:
        r = self.trace.retrieval
        return bool(r and {sc.chunk.page for sc in r.chunks} & set(self.case.pages))

    @property
    def correct(self) -> bool:
        if not self.outcome_ok:
            return False
        if self.case.expected == "not_found":
            return True
        return self.citation_ok and self.content_ok


def load_ask_cases(path: Path = ASK_CASES) -> list[AskCase]:
    return _load(path, AskCase)


async def index_eval_documents(retrieval: Retrieval, names: set[str]) -> dict[str, DocumentInfo]:
    documents = {}
    for name in sorted(names):
        loaded = load_document(DOCUMENTS / f"{name}.json")
        await retrieval.indexer.index(
            document_id=loaded.id, name=loaded.name, type=loaded.type, pages=loaded.pages
        )
        documents[name] = DocumentInfo(
            id=loaded.id, name=loaded.name, type=loaded.type, pages=len(loaded.pages)
        )
    return documents


async def run_ask_cases(
    workflow: AskWorkflow,
    cases: list[AskCase],
    documents: dict[str, DocumentInfo],
    concurrency: int = 3,
) -> list[AskCaseResult]:
    gate = asyncio.Semaphore(concurrency)

    async def one(case: AskCase) -> AskCaseResult:
        trace = AskTrace()
        request = OrchestratorRequest(
            message=case.question, history=_turns(case.history), document=documents[case.document]
        )
        async with gate:
            try:
                async for _ in workflow.run(request, trace):
                    pass
            except OrchestratorError as exc:
                return AskCaseResult(case, trace, exc.code)
        return AskCaseResult(case, trace)

    return list(await asyncio.gather(*(one(c) for c in cases)))


def _ratio(hits: int, total: int) -> str:
    return f"{hits}/{total} ({hits / total:.0%})" if total else "n/a"


def ask_report(results: list[AskCaseResult]) -> str:
    answerable = [r for r in results if r.case.expected == "answered"]
    unanswerable = [r for r in results if r.case.expected == "not_found"]
    answered = [r for r in results if r.outcome == "answered"]
    lines = [
        f"Overall correct:            {_ratio(sum(r.correct for r in results), len(results))}",
        "",
        "BRD §6 targets:",
        f"  answer correctness ≥ 80%   "
        f"{_ratio(sum(r.correct for r in answerable), len(answerable))}",
        f"  correct citation   ≥ 90%   "
        f"{_ratio(sum(r.citation_ok for r in answerable), len(answerable))}",
        f"  'not found' right  ≥ 90%   "
        f"{_ratio(sum(r.outcome_ok for r in unanswerable), len(unanswerable))}",
        "",
        f"Retrieval recall (expected page in top N): "
        f"{_ratio(sum(r.retrieved for r in answerable), len(answerable))}",
        f"Uncited answers (should be 0): "
        f"{sum('uncited_answer' in r.trace.warnings for r in answered)}",
        f"Stopped by the reranker gate: {sum(r.trace.gated for r in results)}",
        f"Rewritten follow-ups: "
        f"{sum(1 for r in results if r.trace.rewrite and r.trace.rewrite.rewritten)}",
        "",
    ]
    for r in results:
        if r.correct:
            continue
        lines.append(f"MISS [{r.case.id}] {r.case.question}")
        if r.error:
            lines.append(f"       error: {r.error}")
        if not r.outcome_ok:
            lines.append(f"       outcome {r.outcome}, expected {r.case.expected}")
        if r.case.expected == "answered" and r.outcome == "answered":
            if not r.citation_ok:
                lines.append(
                    f"       cited pages {sorted(r.cited_pages)}, expected one of {r.case.pages}"
                    f" (retrieved: {'yes' if r.retrieved else 'NO'})"
                )
            if not r.content_ok:
                lines.append(f"       content check failed: {r.case.must_include}")
        if r.trace.rewrite and r.trace.rewrite.rewritten:
            lines.append(f"       rewritten: {r.trace.rewrite.query}")
        if r.text:
            lines.append(f"       answer: {strip_markers(r.text)[:300]}")
    gens = [r.trace.generation for r in results if r.trace.generation]
    if gens:
        first = [g.first_token_ms for g in gens if g.first_token_ms is not None]
        total_in = sum(g.usage.input_tokens for g in gens)
        total_out = sum(g.usage.output_tokens for g in gens)
        cost = estimate_cost(gens[0].requested_model, total_in, total_out)
        rewrites = [r.trace.rewrite for r in results if r.trace.rewrite and r.trace.rewrite.model]
        cost += sum(
            estimate_cost(x.model, x.usage.input_tokens, x.usage.output_tokens) for x in rewrites
        )
        lines += [
            "",
            f"Latency (generation): first text p50 {_percentile(first, 0.5):.0f} ms, "
            f"p95 {_percentile(first, 0.95):.0f} ms; full answer p50 "
            f"{_percentile([g.latency_ms for g in gens], 0.5):.0f} ms",
            f"Generation tokens: {total_in:,} in, {total_out:,} out. "
            f"Estimated cost incl. rewrites: ~${cost:.3f}",
        ]
    return "\n".join(lines)


def ask_results_json(results: list[AskCaseResult]) -> str:
    return json.dumps(
        [
            {
                "id": r.case.id,
                "expected": r.case.expected,
                "outcome": r.outcome,
                "correct": r.correct,
                "citation_ok": r.citation_ok,
                "content_ok": r.content_ok,
                "retrieved": r.retrieved,
                "gated": r.trace.gated,
                "query": r.trace.rewrite.query if r.trace.rewrite else None,
                "cited_pages": sorted(r.cited_pages),
                "best_score": r.trace.retrieval.best_score if r.trace.retrieval else None,
                "answer": r.text,
                "warnings": r.trace.warnings,
                "error": r.error,
            }
            for r in results
        ],
        indent=2,
        ensure_ascii=False,
    )
