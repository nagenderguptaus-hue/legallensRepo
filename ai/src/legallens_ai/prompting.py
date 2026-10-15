"""Helpers shared by every prompt: loading ``*.prompt.md`` files and framing untrusted text.

Anything the lawyer typed, or that came from a document, goes into the prompt inside XML tags
with ``<`` / ``>`` / ``&`` escaped, so it can't open or close the tags that frame it (NFR-6).
"""

import html
from collections.abc import Sequence
from pathlib import Path

from legallens_ai.schemas import Turn

PROMPTS_DIR = Path(__file__).parent / "prompts"
TRUNCATED = " …[truncated]"


def load_prompt(name_or_path: str | Path) -> str:
    """``load_prompt("ask")`` reads ``prompts/ask.prompt.md``. The file must not be empty."""
    path = (
        name_or_path
        if isinstance(name_or_path, Path)
        else PROMPTS_DIR / f"{name_or_path}.prompt.md"
    )
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"Prompt file is empty: {path}")
    return text


def clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit].rstrip() + TRUNCATED


def escape(text: str) -> str:
    """Stops untrusted text from opening or closing the XML tags that frame it."""
    return html.escape(text, quote=False)


def render_history(
    history: Sequence[Turn],
    *,
    turns: int,
    turn_chars: int,
    full_turn_index: int | None = None,
) -> list[str]:
    """The last ``turns`` turns as ``<turn>`` lines inside ``<conversation_history>``.

    Each turn is cut to ``turn_chars``, except the turn at ``full_turn_index`` (an index into
    ``history``), which is kept whole: Draft uses it for the draft being revised.
    Returns no lines when there is no history to show.
    """
    if turns <= 0 or not history:
        return []
    start = max(0, len(history) - turns)
    lines = ["<conversation_history>"]
    for index in range(start, len(history)):
        turn = history[index]
        attrs = f'role="{turn.role}"'
        if turn.role == "assistant" and turn.intent:
            attrs += f' intent="{turn.intent}"'
        text = turn.content.strip() if index == full_turn_index else clip(turn.content, turn_chars)
        lines.append(f"<turn {attrs}>{escape(text)}</turn>")
    lines.append("</conversation_history>")
    return lines
