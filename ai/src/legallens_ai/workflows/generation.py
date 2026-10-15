"""Streaming generation with Claude's native citations (W22-W23), shared by all workflows.

Chunks go to Claude as ``search_result`` blocks: ``source`` is the chunk id and each paragraph
is its own text block, so a citation points at whole paragraphs (``cited_text`` is copied by
the API from what we sent, never written by the model).

While the answer streams, a citation arrives at the start of the text block it supports. This
module numbers each distinct cited passage ``[n]`` (the same passage keeps its number), emits a
``CitationEvent`` the first time a number is used, and writes `` [n]`` into the text where the
cited block ends. Trailing whitespace is held back until the next text, so a marker never lands
on its own line.
"""

import logging
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import anthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from legallens_ai.errors import ModelRefusedError
from legallens_ai.events import CitationEvent, TokenEvent
from legallens_ai.llm import map_anthropic_error
from legallens_ai.retrieval.chunker import SECTION_CHARS, is_heading
from legallens_ai.retrieval.types import Chunk
from legallens_ai.schemas import TokenUsage
from legallens_ai.streams import closing

log = logging.getLogger("legallens_ai.generation")


def search_result_block(chunk: Chunk, *, document_name: str, cache: bool = False) -> dict[str, Any]:
    title = " · ".join(p for p in (document_name, f"p. {chunk.page}", chunk.section) if p)
    block: dict[str, Any] = {
        "type": "search_result",
        "source": chunk.chunk_id,
        "title": title,
        "content": [{"type": "text", "text": p} for p in chunk.paragraphs],
        "citations": {"enabled": True},
    }
    if cache:  # prompt-cache everything up to and including this block (W31)
        block["cache_control"] = {"type": "ephemeral"}
    return block


def build_messages(
    system_prompt: str,
    chunks: Sequence[Chunk],
    *,
    document_name: str,
    text: str,
    cache_document: bool = False,
) -> list[BaseMessage]:
    blocks: list[dict[str, Any]] = [
        search_result_block(
            c, document_name=document_name, cache=cache_document and i == len(chunks) - 1
        )
        for i, c in enumerate(chunks)
    ]
    blocks.append({"type": "text", "text": text})
    return [SystemMessage(content=system_prompt), HumanMessage(content=blocks)]  # type: ignore[arg-type]


@dataclass
class GenerationTrace:
    requested_model: str
    model: str | None = None  # the model that answered (differs after a refusal fallback)
    text: str = ""  # the full answer, markers included
    citations: list[CitationEvent] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)
    cache_read_tokens: int = 0
    stop_reason: str | None = None
    first_token_ms: float | None = None
    latency_ms: float = 0.0


def section_of(chunk: Chunk, paragraph: int) -> str | None:
    """The section a paragraph is in: the nearest heading at or above it in the chunk, else
    the chunk's own section. A chunk can span several sections, so this is per citation."""
    for text in reversed(chunk.paragraphs[: paragraph + 1]):
        if is_heading(text):
            return text[:SECTION_CHARS]
    return chunk.section


class CitationNumbering:
    """Gives each distinct cited passage a stable ``[n]``."""

    def __init__(self, chunks: Sequence[Chunk]) -> None:
        self._chunks = {c.chunk_id: c for c in chunks}
        self._numbers: dict[tuple[str, int, int], int] = {}
        self.events: list[CitationEvent] = []

    def number(self, citation: dict[str, Any]) -> tuple[int | None, CitationEvent | None]:
        """(n, event) — event is set only the first time this passage is cited."""
        chunk = self._chunks.get(str(citation.get("source", "")))
        if chunk is None:
            return None, None
        start = int(citation.get("start_block_index", 0))
        end = int(citation.get("end_block_index", start + 1))
        key = (chunk.chunk_id, start, end)
        if key in self._numbers:
            return self._numbers[key], None
        n = len(self._numbers) + 1
        self._numbers[key] = n
        # cited_text is exactly these paragraphs, but run together with no separator.
        quote = "\n\n".join(chunk.paragraphs[start:end]) or str(citation.get("cited_text", ""))
        event = CitationEvent(
            index=n,
            document_id=chunk.document_id,
            page=chunk.page,
            quote=quote.strip(),
            section=section_of(chunk, start),
            chunk_id=chunk.chunk_id,
        )
        self.events.append(event)
        return n, event


async def stream_with_citations(
    llm: BaseChatModel,
    messages: list[BaseMessage],
    *,
    chunks: Sequence[Chunk],
    trace: GenerationTrace,
    model_setting: str,
) -> AsyncIterator[TokenEvent | CitationEvent]:
    numbering = CitationNumbering(chunks)
    started = time.perf_counter()
    current_block: Any = object()
    pending: list[int] = []  # markers owed to the current text block
    held_ws = ""  # trailing whitespace not yet emitted
    parts: list[str] = []
    input_tokens = output_tokens = cache_read = 0

    def emit(text: str) -> TokenEvent:
        if trace.first_token_ms is None:
            trace.first_token_ms = (time.perf_counter() - started) * 1000
        parts.append(text)
        return TokenEvent(text)

    def markers() -> str:
        text = " " + "".join(f"[{n}]" for n in pending)
        pending.clear()
        return text

    try:
        # When the user presses Stop, the HTTP stream to the model closes at once.
        async with closing(llm.astream(messages)) as stream:
            async for chunk in stream:
                if chunk.usage_metadata:
                    input_tokens += chunk.usage_metadata.get("input_tokens", 0)
                    output_tokens += chunk.usage_metadata.get("output_tokens", 0)
                    details = chunk.usage_metadata.get("input_token_details") or {}
                    cache_read += details.get("cache_read", 0) or 0
                meta = chunk.response_metadata or {}
                trace.stop_reason = meta.get("stop_reason") or trace.stop_reason
                trace.model = meta.get("model_name") or meta.get("model") or trace.model

                content = chunk.content
                blocks = (
                    [{"type": "text", "text": content}] if isinstance(content, str) else content
                )
                for block in blocks:
                    if not isinstance(block, dict) or block.get("type") != "text":
                        continue  # thinking blocks are never shown
                    index = block.get("index")
                    if index != current_block:
                        if pending:
                            yield emit(markers())
                        current_block = index
                    for citation in block.get("citations") or []:
                        if not isinstance(citation, dict):
                            continue
                        n, event = numbering.number(citation)
                        if event is not None:
                            yield event
                        if n is not None and n not in pending:
                            pending.append(n)
                    text = block.get("text") or ""
                    body = text.rstrip()
                    if body:
                        yield emit(held_ws + body)
                        held_ws = text[len(body) :]
                    else:
                        held_ws += text
        if pending:
            yield emit(markers())
    except anthropic.APIError as exc:
        raise map_anthropic_error(
            exc, log=log, event="generation_model", model_setting=model_setting
        ) from exc

    trace.text = "".join(parts)
    trace.citations = numbering.events
    trace.usage = TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens)
    trace.cache_read_tokens = cache_read
    trace.latency_ms = (time.perf_counter() - started) * 1000
    log.info(
        "generated model=%s stop_reason=%s citations=%d latency_ms=%.0f first_token_ms=%s "
        "input_tokens=%d output_tokens=%d cache_read=%d",
        trace.model,
        trace.stop_reason,
        len(trace.citations),
        trace.latency_ms,
        f"{trace.first_token_ms:.0f}" if trace.first_token_ms is not None else None,
        input_tokens,
        output_tokens,
        cache_read,
    )
    if trace.stop_reason == "refusal":
        raise ModelRefusedError()
    if trace.stop_reason == "max_tokens":
        log.warning("generation_truncated model=%s", trace.model)
