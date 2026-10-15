"""The Clarify reply: the router found the message unclear (FR-22), so offer the options.

A fixed template, no model call (orchestration.todo.md O7): the router has already spent one
call deciding the message is unclear, and a predictable reply is instant. The suggestions are
shown as chips under the reply; each one routes cleanly when clicked.
"""

from collections.abc import AsyncIterator

from legallens_ai.events import DoneEvent, StatusEvent, TokenEvent, WorkflowEvent
from legallens_ai.schemas import OrchestratorRequest

WITH_DOCUMENT_SUGGESTIONS = (
    "Summarize this document",
    "What are the key obligations?",
    "Draft a memo based on this document",
)
# Without a document only drafting works (FR-15); Ask and Summary need one.
NO_DOCUMENT_SUGGESTIONS = (
    "Draft a legal memo",
    "Draft a case brief",
    "Draft a demand letter",
)


def clarify_text(request: OrchestratorRequest) -> str:
    if request.document is not None:
        return (
            f"I can help with **{request.document.name}** in a few ways: answer a question "
            "about it, summarize it, or draft a memo or brief based on it. "
            "What would you like to do?"
        )
    return (
        "I can answer questions about a document, summarize it, or draft a memo, case brief "
        "or letter. What would you like to do? To ask about or summarize a document, upload "
        "one or pick a Ready document from the library first."
    )


class ClarifyWorkflow:
    async def run(self, request: OrchestratorRequest) -> AsyncIterator[WorkflowEvent]:
        yield StatusEvent("Understanding your request")
        yield TokenEvent(clarify_text(request))
        suggestions = (
            WITH_DOCUMENT_SUGGESTIONS if request.document is not None else NO_DOCUMENT_SUGGESTIONS
        )
        yield DoneEvent("clarify", suggestions)
