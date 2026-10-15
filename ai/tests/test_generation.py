from typing import cast

import anthropic
import httpx2
import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessageChunk

from legallens_ai.errors import ModelRefusedError, ModelUnavailableError
from legallens_ai.events import CitationEvent, TokenEvent
from legallens_ai.retrieval.types import Chunk
from legallens_ai.workflows.checks import (
    NOT_FOUND,
    check_draft,
    check_summary,
    is_not_found,
    strip_markers,
)
from legallens_ai.workflows.generation import (
    GenerationTrace,
    build_messages,
    stream_with_citations,
)
from tests.workflow_fakes import FakeStreamingLLM, citation, final_chunk, text_chunk

CHUNKS = [
    Chunk(
        "d:00000",
        "d",
        0,
        3,
        "5. Early Termination",
        ("5. Early Termination", "Tenant may end.", "Fee applies."),
    ),
    Chunk("d:00001", "d", 1, 2, "3. Rent", ("Rent is $4,500.",)),
]


async def run(fake: FakeStreamingLLM) -> tuple[list[TokenEvent | CitationEvent], GenerationTrace]:
    trace = GenerationTrace(requested_model="claude-sonnet-5-5")
    events = [
        e
        async for e in stream_with_citations(
            cast(BaseChatModel, fake),
            [],
            chunks=CHUNKS,
            trace=trace,
            model_setting="LL_AI_ASK_MODEL",
        )
    ]
    return events, trace


async def test_citations_become_numbered_markers_at_the_end_of_the_cited_block() -> None:
    # Same shape as the live Sonnet 5.5 stream: the citation arrives first, then the text.
    fake = FakeStreamingLLM(
        [
            text_chunk(0, "", [citation("d:00000", 1, 2, "Tenant may end.")]),
            text_chunk(0, "Yes, the tenant may"),
            text_chunk(0, " end the lease."),
            text_chunk(1, "\n\n"),
            text_chunk(2, "", [citation("d:00000", 2, 3, "Fee applies.")]),
            text_chunk(2, "A fee applies."),
            text_chunk(3, " Rent is unchanged"),
            text_chunk(4, "", [citation("d:00000", 1, 2, "Tenant may end.")]),
            text_chunk(4, " (see above)."),
            final_chunk(),
        ]
    )
    events, trace = await run(fake)
    assert trace.text == (
        "Yes, the tenant may end the lease. [1]\n\nA fee applies. [2] Rent is unchanged"
        " (see above). [1]"
    )
    citations = [e for e in events if isinstance(e, CitationEvent)]
    assert [(c.index, c.page, c.quote) for c in citations] == [
        (1, 3, "Tenant may end."),
        (2, 3, "Fee applies."),
    ]  # the repeated passage is not re-announced
    assert citations[0].section == "5. Early Termination"
    assert citations[0].chunk_id == "d:00000"
    # the citation event is emitted before the text that cites it
    assert isinstance(events[0], CitationEvent)
    assert trace.model == "claude-sonnet-5-5"
    assert trace.stop_reason == "end_turn"
    assert trace.usage.output_tokens == 50
    assert trace.first_token_ms is not None


async def test_unknown_sources_and_thinking_blocks_are_ignored() -> None:
    fake = FakeStreamingLLM(
        [
            AIMessageChunk(content=[{"type": "thinking", "thinking": "secret", "index": 0}]),
            text_chunk(1, "", [citation("not-a-chunk")]),
            text_chunk(1, "Plain."),
            final_chunk(),
        ]
    )
    events, trace = await run(fake)
    assert trace.text == "Plain."
    assert not [e for e in events if isinstance(e, CitationEvent)]


async def test_refusal_raises() -> None:
    fake = FakeStreamingLLM([text_chunk(0, "Partial"), final_chunk(stop_reason="refusal")])
    with pytest.raises(ModelRefusedError):
        await run(fake)


async def test_api_error_mid_stream_is_mapped() -> None:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    fake = FakeStreamingLLM([text_chunk(0, "Partial")], error=anthropic.APITimeoutError(request))
    with pytest.raises(ModelUnavailableError):
        await run(fake)


def test_chunks_are_sent_as_cited_search_results_with_paragraph_blocks() -> None:
    messages = build_messages(
        "SYSTEM",
        CHUNKS,
        document_name="Lease.pdf",
        text="<question>q</question>",
        cache_document=True,
    )
    assert messages[0].content == "SYSTEM"
    blocks = messages[1].content
    assert isinstance(blocks, list)
    first, second, question = blocks
    assert isinstance(first, dict) and isinstance(second, dict) and isinstance(question, dict)
    assert first["type"] == "search_result"
    assert first["source"] == "d:00000"
    assert first["title"] == "Lease.pdf · p. 3 · 5. Early Termination"
    assert [b["text"] for b in first["content"]] == list(CHUNKS[0].paragraphs)
    assert first["citations"] == {"enabled": True}
    assert "cache_control" not in first
    assert second["cache_control"] == {"type": "ephemeral"}  # cache breakpoint on the last block
    assert question == {"type": "text", "text": "<question>q</question>"}


# ---------------------------------------------------------------- checks


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (NOT_FOUND, True),
        ("I couldn’t find this in the document. [1]", True),
        ("  i couldn't find this in the document", True),
        ("The lease says I couldn't find this in the document.", False),
        ("Yes. [1]", False),
    ],
)
def test_not_found_detection(text: str, expected: bool) -> None:
    assert is_not_found(text) is expected


def test_strip_markers() -> None:
    assert strip_markers("Rent is due [1][2]. Late fee [3].") == "Rent is due. Late fee."


SUMMARY = """## Document type & purpose
A commercial lease. [1]

## Parties
- Harbor Properties LLC (Landlord) [2]

## Key dates & deadlines
Not found in document.

## Key terms / obligations / holdings
- Rent of $4,500 per month.

## Plain-language overview
A five-year shop lease. [1]
"""


def test_summary_check_finds_missing_and_uncited_sections() -> None:
    results = {r.heading: r for r in check_summary(SUMMARY)}
    assert results["Document type & purpose"].ok
    assert results["Key dates & deadlines"].not_found and results["Key dates & deadlines"].ok
    assert not results["Key terms / obligations / holdings"].ok  # present, uncited
    assert results["Key terms / obligations / holdings"].present
    assert not results["Notable risks"].present


def test_draft_check_counts_placeholders_and_flags_invented_authorities() -> None:
    text = (
        "Under Cal. Civ. Code § 1671 [CITATION NEEDED: liquidated damages rule], see "
        "Smith v. Jones, 550 U.S. 544 (2007). The notice was sent [CONFIRM: date]. "
        "The lease itself cites Harbor v. Maple. [CITATION NEEDED: Hadley v. Baxendale]"
    )
    sources = ["Instructions mention Cal. Civ. Code § 1671.", "Lease text: Harbor v. Maple."]
    result = check_draft(text, sources)
    assert result.placeholders == 3
    # In the sources (fine), inside a placeholder (fine), or invented (flagged):
    assert result.invented_citations == ("Smith v. Jones", "550 U.S. 544")


async def test_citation_section_is_the_heading_above_the_cited_paragraph() -> None:
    chunk = Chunk(
        "d:00009",
        "d",
        9,
        12,
        "12. Non-Solicitation",
        (
            "12. Non-Solicitation",
            "No poaching.",
            "13. General",
            "13.1 New York law governs.",
            "More.",
        ),
    )
    fake = FakeStreamingLLM(
        [
            text_chunk(0, "", [citation("d:00009", 3, 5, "13.1 New York law governs.More.")]),
            text_chunk(0, "New York."),
            text_chunk(1, "", [citation("d:00009", 1, 2)]),
            text_chunk(1, " No poaching."),
            final_chunk(),
        ]
    )
    trace = GenerationTrace(requested_model="m")
    events = [
        e
        async for e in stream_with_citations(
            cast(BaseChatModel, fake), [], chunks=[chunk], trace=trace, model_setting="X"
        )
    ]
    first, second = [e for e in events if isinstance(e, CitationEvent)]
    assert first.section == "13. General"
    assert first.quote == "13.1 New York law governs.\n\nMore."  # paragraphs kept apart
    assert second.section == "12. Non-Solicitation"
