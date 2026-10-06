"""Request context middleware (pure ASGI, so it never buffers streamed responses).

- Assigns a request id (reuses a well-formed incoming ``X-Request-ID``), binds it to every log
  line and returns it in the ``X-Request-ID`` response header.
- Writes one access-log line per request with status and latency (NFR-10).
- Turns any unhandled exception into the standard 500 envelope; the stack trace is logged,
  never returned.
"""

import json
import re
import time

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from legallens.ids import new_id

log = structlog.get_logger("legallens.http")

_VALID_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get("x-request-id", "")
        request_id = incoming if _VALID_ID.match(incoming) else new_id("req")
        scope.setdefault("state", {})["request_id"] = request_id
        status = 500
        response_started = False
        start = time.perf_counter()

        async def send_with_id(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        with structlog.contextvars.bound_contextvars(request_id=request_id):
            try:
                await self.app(scope, receive, send_with_id)
            except Exception:
                log.exception("unhandled_error", method=scope["method"], path=scope["path"])
                if not response_started:
                    body = json.dumps(
                        {
                            "code": "internal_error",
                            "message": "Something went wrong on our side. Try again.",
                            "request_id": request_id,
                        }
                    ).encode()
                    await send_with_id(
                        {
                            "type": "http.response.start",
                            "status": 500,
                            "headers": [
                                (b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode()),
                            ],
                        }
                    )
                    await send_with_id({"type": "http.response.body", "body": body})
            finally:
                log.info(
                    "request",
                    method=scope["method"],
                    path=scope["path"],
                    status=status,
                    ms=round((time.perf_counter() - start) * 1000, 1),
                )
