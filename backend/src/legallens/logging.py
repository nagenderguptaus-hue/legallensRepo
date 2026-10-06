"""Structured JSON logging (NFR-10).

Rule (NFR-5): log ids and metadata only. Never request bodies, document text, prompts,
answers or file names.
"""

import logging
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import structlog

from legallens.ids import new_id

log = structlog.get_logger("legallens")


def configure_logging(level: str = "INFO", json: bool = True) -> None:
    renderer: Any = structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=False,
    )


def current_request_id() -> str:
    """Request id of the current request, or a fresh one for background work."""
    value = structlog.contextvars.get_contextvars().get("request_id")
    return value if isinstance(value, str) else new_id("req")


@contextmanager
def timed(step: str, **fields: Any) -> Iterator[None]:
    """Logs how long a step took, e.g. ``with timed("ingestion.extract", document_id=...)``."""
    start = time.perf_counter()
    try:
        yield
    finally:
        log.info(
            "step_timing", step=step, ms=round((time.perf_counter() - start) * 1000, 1), **fields
        )
