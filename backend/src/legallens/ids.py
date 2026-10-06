"""Identifier and timestamp helpers shared by every layer."""

import secrets
from datetime import UTC, datetime


def new_id(prefix: str) -> str:
    """Opaque prefixed id, e.g. ``doc_3f9a1c0b7d2e4a56``."""
    return f"{prefix}_{secrets.token_hex(8)}"


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime) -> str:
    """Fixed-width ISO 8601 UTC with milliseconds (``2026-10-05T14:03:22.418Z``).

    Fixed width matters: the frontend sorts these strings lexically.
    """
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso() -> str:
    return iso(utc_now())
