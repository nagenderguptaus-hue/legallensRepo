"""Live end-to-end check of AI chat through the real backend (orchestration.todo.md G9).

Opt-in, because it calls the Anthropic API (~$0.25 per run) and needs the search models
(bge-large-en-v1.5 + bge-reranker-v2-m3, ~4 GB, downloaded into ai/data/models on first use):

    uv run pytest -m live -s

Everything is real: the adapter factories (as loaded from LL_ORCHESTRATOR / LL_INGESTION),
ingestion, the index, the router, the workflows and Claude. The ``ai_turn`` log lines it prints
(with ``-s``) carry the per-step timings and token counts of each turn.
"""

import re
from typing import Any

import pytest

pytest.importorskip("legallens_ai", reason="needs the AI layer: uv sync --extra ai")
from legallens.adapters.ai import INGESTION_FACTORY, stack_for
from tests.conftest import RunApp, Running, parse_sse

pytestmark = pytest.mark.live

# run_app's own ``orchestrator=`` argument takes an object, so the setting goes in via the
# environment (as in a real deployment).
ORCHESTRATOR_FACTORY = "legallens.adapters.ai:create_orchestrator"
AI = {
    "ingestion": INGESTION_FACTORY,
    "log_level": "INFO",
    "stream_first_event_timeout_s": 45,
    "stream_total_timeout_s": 600,
}
SUMMARY_HEADINGS = (
    "Document type",
    "Parties",
    "Key dates",
    "Key terms",
    "Notable risks",
    "Plain-language overview",
)


async def turn(
    r: Running, conversation_id: str, message: str, document_id: str | None
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    res = await r.chat(conversation_id, message, [document_id] if document_id else [])
    assert res.status_code == 200, res.text
    events = parse_sse(res.text)
    assert events[-1][0] == "done", events[-1]
    text = "".join(d["text"] for n, d in events if n == "token")
    citations = [d for n, d in events if n == "citation"]
    return text, citations, {"intent": events[0][1]["intent"], **events[-1][1]}


async def test_full_chat_flow_on_the_nda(run_app: RunApp, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LL_ORCHESTRATOR", ORCHESTRATOR_FACTORY)
    async with run_app(**AI) as r:
        assert r.settings.orchestrator == ORCHESTRATOR_FACTORY
        stack = stack_for(r.settings)
        doc = await r.ready_document()  # the synthetic 3-page NDA, through AI ingestion
        await stack.wait_startup()
        health = (await r.client.get("/api/health")).json()
        assert (health["modelRuntime"], health["processing"]) == ("ready", "cloud")

        conversation = (await r.new_conversation())["id"]

        text, cites, done = await turn(
            r, conversation, "How long does the agreement remain in effect?", doc["id"]
        )
        assert (done["intent"], done["outcome"]) == ("ask", "answered")
        assert re.search(r"three|\b3\b", text, re.IGNORECASE)
        assert 2 in {c["page"] for c in cites}

        # Follow-up: needs the rewriter to resolve "it".
        text, cites, done = await turn(r, conversation, "Can either party end it early?", doc["id"])
        assert (done["intent"], done["outcome"]) == ("ask", "answered")
        assert 3 in {c["page"] for c in cites}

        _, cites, done = await turn(r, conversation, "What is the monthly rent?", doc["id"])
        assert (done["intent"], done["outcome"]) == ("ask", "not_found")
        assert cites == []

        text, cites, done = await turn(r, conversation, "Summarize this document", doc["id"])
        assert (done["intent"], done["outcome"]) == ("summary", "answered")
        for heading in SUMMARY_HEADINGS:
            assert heading.lower() in text.lower(), heading
        assert cites

        text, _, done = await turn(
            r, conversation, "Draft a short memo on the termination rights in this NDA", doc["id"]
        )
        assert (done["intent"], done["outcome"]) == ("draft", "answered")
        assert "MEMO" in text.upper()

        _, _, done = await turn(r, conversation, "hmm", doc["id"])
        assert done["outcome"] == "clarify" and done["suggestions"]

        # Deleting the document purges its chunks and vectors (FR-5).
        assert (await r.client.delete(f"/api/documents/{doc['id']}")).status_code == 204
        retrieval = await stack.runtime.retrieval()
        assert await retrieval.store.chunks(doc["id"]) == []
