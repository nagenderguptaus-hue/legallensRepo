"""Runs the labelled intent cases against the real classifier and scores the results."""

import asyncio
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from legallens_ai.errors import OrchestratorError
from legallens_ai.intent_classifier import IntentClassifier
from legallens_ai.schemas import INTENTS, Intent, Turn

DEFAULT_CASES = Path(__file__).resolve().parents[2] / "evals" / "intent_cases.jsonl"

# Claude Haiku 4.5 list prices, USD per million tokens (for the cost estimate only).
HAIKU_INPUT_PER_M = 1.00
HAIKU_OUTPUT_PER_M = 5.00


class CaseTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str
    content: str
    intent: Intent | None = None


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    message: str
    expected: Intent
    history: list[CaseTurn] = []
    note: str | None = None

    def turns(self) -> list[Turn]:
        return [
            Turn(
                role="user" if t.role == "user" else "assistant", content=t.content, intent=t.intent
            )
            for t in self.history
        ]


@dataclass(frozen=True)
class CaseResult:
    case: Case
    predicted: Intent | None  # None when the call failed
    rationale: str
    error: str | None
    latency_ms: float
    input_tokens: int
    output_tokens: int

    @property
    def correct(self) -> bool:
        return self.predicted == self.case.expected


def load_cases(path: Path = DEFAULT_CASES) -> list[Case]:
    cases: list[Case] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                cases.append(Case.model_validate_json(line))
            except ValueError as exc:
                raise ValueError(f"{path.name}:{number}: {exc}") from exc
    ids = Counter(c.id for c in cases)
    if dupes := [i for i, n in ids.items() if n > 1]:
        raise ValueError(f"Duplicate case ids: {dupes}")
    return cases


async def run_cases(
    classifier: IntentClassifier, cases: list[Case], concurrency: int = 4
) -> list[CaseResult]:
    gate = asyncio.Semaphore(concurrency)

    async def one(case: Case) -> CaseResult:
        async with gate:
            try:
                r = await classifier.classify(case.message, case.turns())
            except OrchestratorError as exc:
                return CaseResult(case, None, "", exc.code, 0.0, 0, 0)
            return CaseResult(
                case,
                r.intent,
                r.rationale,
                None,
                r.latency_ms,
                r.usage.input_tokens,
                r.usage.output_tokens,
            )

    return list(await asyncio.gather(*(one(c) for c in cases)))


def report(results: list[CaseResult]) -> str:
    total = len(results)
    correct = sum(r.correct for r in results)
    lines = [f"Accuracy: {correct}/{total} ({correct / total:.0%})", ""]

    lines.append("Per intent (recall):")
    for intent in INTENTS:
        rows = [r for r in results if r.case.expected == intent]
        if rows:
            hit = sum(r.correct for r in rows)
            lines.append(f"  {intent:<8} {hit}/{len(rows)}")
    lines.append("")

    labels: list[str] = [*INTENTS, "error"]
    lines.append("Confusion matrix (rows = expected, columns = predicted):")
    lines.append("  " + " " * 9 + "".join(f"{label:>9}" for label in labels))
    for expected in INTENTS:
        counts: Counter[str] = Counter(
            r.predicted or "error" for r in results if r.case.expected == expected
        )
        lines.append(f"  {expected:<9}" + "".join(f"{counts.get(lb, 0):>9}" for lb in labels))
    lines.append("")

    misses = [r for r in results if not r.correct]
    if misses:
        lines.append("Misses:")
        for r in misses:
            got = r.predicted or f"error ({r.error})"
            lines.append(f"  [{r.case.id}] expected {r.case.expected}, got {got}")
            lines.append(f"      message:   {r.case.message}")
            if r.rationale:
                lines.append(f"      rationale: {r.rationale}")
            if r.case.note:
                lines.append(f"      note:      {r.case.note}")
        lines.append("")

    ok = [r for r in results if r.error is None]
    tokens_in = sum(r.input_tokens for r in ok)
    tokens_out = sum(r.output_tokens for r in ok)
    cost = tokens_in / 1e6 * HAIKU_INPUT_PER_M + tokens_out / 1e6 * HAIKU_OUTPUT_PER_M
    if ok:
        latencies = sorted(r.latency_ms for r in ok)
        p50 = latencies[len(latencies) // 2]
        p95 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))]
        lines.append(f"Latency: p50 {p50:.0f} ms, p95 {p95:.0f} ms")
    lines.append(f"Tokens: {tokens_in:,} in, {tokens_out:,} out (~${cost:.4f} at Haiku 4.5 prices)")
    return "\n".join(lines)


def to_json(results: list[CaseResult]) -> str:
    return json.dumps(
        [
            {
                "id": r.case.id,
                "expected": r.case.expected,
                "predicted": r.predicted,
                "correct": r.correct,
                "rationale": r.rationale,
                "error": r.error,
                "latency_ms": round(r.latency_ms),
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
            }
            for r in results
        ],
        indent=2,
    )
