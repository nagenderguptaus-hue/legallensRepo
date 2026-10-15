"""Closing async streams promptly.

When the user presses Stop, the backend closes the orchestrator's stream. Each layer must then
close the stream it is reading from, down to the HTTP stream to the model, so no more tokens
are generated (or billed). ``async for`` alone leaves an abandoned inner stream open until it
is garbage-collected.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


@asynccontextmanager
async def closing[T](stream: AsyncIterator[T]) -> AsyncIterator[AsyncIterator[T]]:
    """Like ``contextlib.aclosing``, for any async iterator (typed as such or not)."""
    try:
        yield stream
    finally:
        aclose = getattr(stream, "aclose", None)
        if aclose is not None:
            await aclose()
