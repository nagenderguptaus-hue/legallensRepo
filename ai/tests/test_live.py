"""Calls the real Anthropic API. Deselected by default; run with `uv run pytest -m live`."""

from pathlib import Path

import pytest

from legallens_ai.config import AISettings
from legallens_ai.orchestrator import Orchestrator
from legallens_ai.retrieval import open_retrieval
from legallens_ai.retrieval.loaders import load_document
from legallens_ai.schemas import DocumentInfo, OrchestratorRequest
from legallens_ai.workflows import AskTrace, AskWorkflow

pytestmark = pytest.mark.live

DOC = DocumentInfo(id="doc_1", name="Lease.pdf", type="pdf", pages=12)
EVAL_DOCS = Path(__file__).resolve().parents[1] / "evals" / "documents"


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Can the tenant terminate the lease early?", "ask"),
        ("Summarize this lease", "summary"),
        ("Draft a memo on my exit options", "draft"),
        ("hello", "clarify"),
    ],
)
async def test_haiku_routes_the_demo_messages(message: str, expected: str) -> None:
    settings = AISettings()
    if settings.anthropic_api_key is None:
        pytest.skip("ANTHROPIC_API_KEY is not set")
    decision = await Orchestrator.from_settings(settings).route(
        OrchestratorRequest(message=message, document=DOC)
    )
    assert decision.intent == expected
    assert decision.model == "claude-haiku-4-5"
    assert decision.usage.input_tokens > 0


# ---------------------------------------------------------------- workflows (Sonnet 5.5, ~$0.02)


async def test_ask_answers_the_demo_question_and_refuses_the_unanswerable(tmp_path: Path) -> None:
    settings = AISettings()
    if settings.anthropic_api_key is None:
        pytest.skip("ANTHROPIC_API_KEY is not set")
    settings = settings.model_copy(update={"data_dir": tmp_path})  # models stay shared
    retrieval = await open_retrieval(settings)
    try:
        loaded = load_document(EVAL_DOCS / "lease.json")
        await retrieval.indexer.index(
            document_id=loaded.id, name=loaded.name, type=loaded.type, pages=loaded.pages
        )
        doc = DocumentInfo(id=loaded.id, name=loaded.name, type="pdf", pages=len(loaded.pages))
        ask = AskWorkflow.from_settings(
            settings, store=retrieval.store, retriever=retrieval.retriever
        )

        trace = AskTrace()
        request = OrchestratorRequest("Can the tenant terminate the lease early?", document=doc)
        async for _ in ask.run(request, trace):
            pass
        assert trace.outcome == "answered"
        assert trace.generation is not None
        assert 3 in {c.page for c in trace.generation.citations}

        trace = AskTrace()
        request = OrchestratorRequest("Does the lease include a non-compete clause?", document=doc)
        async for _ in ask.run(request, trace):
            pass
        assert trace.outcome == "not_found"
    finally:
        await retrieval.close()
