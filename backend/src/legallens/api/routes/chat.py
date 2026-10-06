from fastapi import APIRouter

from legallens.api.deps import ContainerDep
from legallens.api.schemas import ApiErrorBody, ChatRequest
from legallens.api.sse import EventStreamResponse

router = APIRouter(prefix="/chat", tags=["chat"])

STREAM_DOC = """Streams one assistant reply as Server-Sent Events.

Events, in order: `intent` (first, with message ids) → `status`* → `token`* → `citation`* →
`done` (or `error`, after which the stream ends). A `: ping` comment is sent every 15 s.
Requests rejected before streaming starts get a normal JSON error envelope."""


@router.post(
    "/stream",
    status_code=200,
    response_class=EventStreamResponse,
    responses={
        200: {"content": {"text/event-stream": {}}, "description": "SSE stream"},
        **{status: {"model": ApiErrorBody} for status in (404, 409, 422, 502, 503, 504)},
    },
    summary="Send a message and stream the reply",
    description=STREAM_DOC,
)
async def chat_stream(body: ChatRequest, c: ContainerDep) -> EventStreamResponse:
    stream = await c.chat.start(body)
    return EventStreamResponse(stream)
