import pytest

from legallens_ai.errors import ModelUnavailableError
from legallens_ai.intent_classifier import IntentClassifier
from legallens_ai.orchestrator import Orchestrator
from legallens_ai.schemas import DocumentInfo, Intent, OrchestratorRequest, Turn
from tests.fakes import FakeStructuredLLM

DOC = DocumentInfo(id="doc_1", name="Lease.pdf", type="pdf", pages=12)


def orchestrator(fake: FakeStructuredLLM) -> Orchestrator:
    return Orchestrator(IntentClassifier(fake.runnable(), model_name="fake-haiku"))


@pytest.mark.parametrize(
    ("intent", "document", "needs_document"),
    [
        ("ask", DOC, False),
        ("ask", None, True),
        ("summary", DOC, False),
        ("summary", None, True),
        ("draft", DOC, False),
        ("draft", None, False),  # drafting works from instructions alone (FR-15)
        ("clarify", None, False),
    ],
)
async def test_route_flags_a_missing_document_only_for_ask_and_summary(
    intent: Intent, document: DocumentInfo | None, needs_document: bool
) -> None:
    decision = await orchestrator(FakeStructuredLLM(intent)).route(
        OrchestratorRequest(message="anything", document=document)
    )
    assert decision.intent == intent
    assert decision.needs_document is needs_document


async def test_route_passes_history_and_reports_metadata() -> None:
    fake = FakeStructuredLLM("draft", "Edit of the previous draft.")
    decision = await orchestrator(fake).route(
        OrchestratorRequest(
            message="make it shorter",
            history=[Turn("user", "Draft a memo"), Turn("assistant", "MEMO", intent="draft")],
            document=DOC,
        )
    )
    assert '<turn role="assistant" intent="draft">MEMO</turn>' in fake.last_user_turn
    assert decision.rationale == "Edit of the previous draft."
    assert decision.model == "fake-haiku"
    assert decision.usage.output_tokens == 40


async def test_document_presence_is_not_shown_to_the_model() -> None:
    """D7: the label must come from the message, not from whether a document is selected."""
    fake = FakeStructuredLLM()
    await orchestrator(fake).route(OrchestratorRequest(message="When is rent due?", document=DOC))
    with_doc = fake.last_user_turn
    await orchestrator(fake).route(OrchestratorRequest(message="When is rent due?"))
    assert fake.last_user_turn == with_doc
    assert "Lease.pdf" not in with_doc


async def test_classifier_errors_propagate() -> None:
    import anthropic
    import httpx2

    error = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://x"))
    with pytest.raises(ModelUnavailableError):
        await orchestrator(FakeStructuredLLM(error=error)).route(
            OrchestratorRequest(message="When is rent due?", document=DOC)
        )
