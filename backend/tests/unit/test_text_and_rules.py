import re

import pytest

from legallens.adapters.standin.rule_based_orchestrator import detect_intent, is_follow_up, to_topic
from legallens.adapters.standin.text import (
    Passage,
    is_heading,
    passages,
    search,
    sentences,
    split_paragraphs,
)
from legallens.ids import iso, new_id, now_iso, utc_now
from legallens.ports.ingestion import PageText
from legallens.services.chat_service import encode_sse, title_from


@pytest.mark.parametrize(
    ("message", "intent"),
    [
        ("Summarize this lease", "summary"),
        ("Give me the key terms", "summary"),
        ("Draft a memo on the termination clause", "draft"),
        ("Please prepare a case brief", "draft"),
        ("hello", "clarify"),
        ("lease?", "ask"),
        ("What is the term of the NDA?", "ask"),
    ],
)
def test_intent_rules_match_the_frontend_mock(message: str, intent: str) -> None:
    assert detect_intent(message) == intent


def test_follow_up_detection() -> None:
    assert is_follow_up("Can they extend it?")
    assert not is_follow_up("What is the governing law of the agreement between Acme and Beta?")


def test_to_topic_strips_the_instruction() -> None:
    assert to_topic("please draft a memo on notice periods") == "Memo on notice periods"
    assert to_topic("draft") == "Legal memorandum"


def test_split_paragraphs_rebuilds_wrapped_lines() -> None:
    text = (
        "1. Term\n"
        "This Agreement shall remain in effect for a period of three years from\n"
        "the Effective Date.\n"
        "Page 2 of 9\n"
        "The parties may renew in writ-\n"
        "ing.\n"
    )
    assert split_paragraphs(text) == [
        "1. Term",
        "This Agreement shall remain in effect for a period of three years from the "
        "Effective Date.",
        "The parties may renew in writing.",
    ]


@pytest.mark.parametrize(
    ("line", "heading"),
    [
        ("ARTICLE IV DEFINITIONS", True),
        ("2. Term", True),
        ("IV. Discussion", True),
        ("CONFIDENTIALITY", True),
        ("1. The Tenant shall pay rent of $5,000 per month.", False),
        ("This is an ordinary sentence.", False),
    ],
)
def test_heading_detection(line: str, heading: bool) -> None:
    assert is_heading(line) is heading


def test_sentences_respect_legal_abbreviations() -> None:
    text = "See Smith v. Jones, No. 12. The court reversed. Costs awarded."
    assert sentences(text) == [
        "See Smith v. Jones, No. 12.",
        "The court reversed.",
        "Costs awarded.",
    ]


CORPUS = passages(
    [
        PageText(1, ["2. Term", "This Agreement lasts three (3) years from the Effective Date."]),
        PageText(2, ["3. Termination", "Either party may terminate with thirty days notice."]),
    ]
)


def test_passages_carry_their_section() -> None:
    assert [
        Passage(1, "2. Term", "This Agreement lasts three (3) years from the Effective Date."),
        Passage(2, "3. Termination", "Either party may terminate with thirty days notice."),
    ] == CORPUS


def test_search_matches_simple_plurals() -> None:
    corpus = passages(
        [PageText(1, ["If Tenant fails to pay rent within ten days, Landlord may terminate."])]
    )
    assert search(corpus, "What happens if the tenant pays rent late?")


def test_search_finds_relevant_passage_and_rejects_unrelated_questions() -> None:
    hits = search(CORPUS, "How do I terminate, and how much notice is needed?")
    assert [h.passage.page for h in hits] == [2]
    assert search(CORPUS, "What is the capital of France?") == []


def test_title_from_first_message() -> None:
    assert title_from("  what is the term of the NDA?  ") == "What is the term of the NDA"
    long = title_from("x" * 100)
    assert len(long) == 48 and long.endswith("…")


def test_sse_encoding_is_one_json_line_per_event() -> None:
    raw = encode_sse("token", {"text": "line one\nline two — ok"}).decode()
    assert raw == 'event: token\ndata: {"text":"line one\\nline two — ok"}\n\n'


def test_ids_and_timestamps_have_fixed_shapes() -> None:
    assert re.fullmatch(r"doc_[0-9a-f]{16}", new_id("doc"))
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", now_iso())
    moment = utc_now().replace(microsecond=5000)
    assert iso(moment).endswith(".005Z")
