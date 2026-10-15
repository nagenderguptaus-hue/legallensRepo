from legallens_ai.evaluation import CaseResult, load_cases, report, run_cases
from legallens_ai.intent_classifier import IntentClassifier, load_system_prompt
from legallens_ai.schemas import INTENTS
from tests.fakes import FakeStructuredLLM


def test_eval_cases_are_valid_and_cover_every_intent() -> None:
    cases = load_cases()
    assert len(cases) >= 40
    assert {c.expected for c in cases} == set(INTENTS)
    for case in cases:
        assert case.message.strip()
        assert all(t.role in ("user", "assistant") for t in case.history)


def test_eval_cases_do_not_copy_the_prompt_examples() -> None:
    """The eval must measure generalisation, so no case message appears in the prompt."""
    prompt = load_system_prompt().lower()
    copied = [c.id for c in load_cases() if f'"{c.message.lower()}"' in prompt]
    assert copied == []


async def test_run_cases_and_report_with_a_fake_model() -> None:
    cases = [c for c in load_cases() if c.id in ("ask-01", "sum-01")]
    classifier = IntentClassifier(FakeStructuredLLM("ask").runnable(), model_name="fake")
    results = await run_cases(classifier, cases)
    assert [r.correct for r in results] == [True, False]
    text = report(results)
    assert "Accuracy: 1/2 (50%)" in text
    assert "[sum-01] expected summary, got ask" in text


def test_report_counts_errors_separately() -> None:
    case = load_cases()[0]
    text = report([CaseResult(case, None, "", "model_unavailable", 0.0, 0, 0)])
    assert "got error (model_unavailable)" in text
