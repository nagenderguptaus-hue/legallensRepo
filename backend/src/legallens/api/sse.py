"""Server-Sent Events response that reacts to the client going away.

When the client disconnects (the user pressed Stop, closed the tab, lost the network) the
stream is cancelled at once, so the reply is saved as ``stopped`` with what was generated so
far. Works with any ASGI server, whatever ASGI spec version it implements.
"""

from collections.abc import AsyncIterator
from typing import Protocol

import anyio
from starlette.responses import Response
from starlette.types import Receive, Scope, Send


class EventSource(Protocol):
    def sse(self) -> AsyncIterator[bytes]: ...

    async def aclose(self) -> None: ...


class EventStreamResponse(Response):
    media_type = "text/event-stream"

    def __init__(self, source: EventSource) -> None:
        self.status_code = 200
        self.background = None
        self._source = source
        self.init_headers({"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        events = self._source.sse()
        try:
            await send(
                {
                    "type": "http.response.start",
                    "status": self.status_code,
                    "headers": self.raw_headers,
                }
            )
            async with anyio.create_task_group() as tg:

                async def watch_disconnect() -> None:
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            tg.cancel_scope.cancel()
                            return

                tg.start_soon(watch_disconnect)
                try:
                    async for chunk in events:
                        await send({"type": "http.response.body", "body": chunk, "more_body": True})
                    await send({"type": "http.response.body", "body": b"", "more_body": False})
                except OSError:
                    pass  # the client went away while we were writing
                tg.cancel_scope.cancel()
        finally:
            with anyio.CancelScope(shield=True):
                aclose = getattr(events, "aclose", None)
                if aclose is not None:
                    await aclose()
                await self._source.aclose()
