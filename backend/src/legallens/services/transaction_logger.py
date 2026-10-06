"""Writes one ``transactions`` row per user action (upload, chat, rename, delete …), with its
request id, outcome and latency. Ids and metadata only, never content (NFR-5)."""

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import structlog

from legallens.db.engine import Database
from legallens.db.models import TransactionRow
from legallens.errors import AppError
from legallens.ids import now_iso
from legallens.logging import current_request_id

log = structlog.get_logger("legallens.transactions")


@dataclass
class Tracked:
    entity_id: str | None = None


class TransactionLogger:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(
        self,
        action: str,
        *,
        status: str,
        latency_ms: float,
        entity_id: str | None = None,
        error_code: str | None = None,
        ttft_ms: float | None = None,
        request_id: str | None = None,
    ) -> None:
        try:
            async with self._db.session() as s:
                s.add(
                    TransactionRow(
                        request_id=request_id or current_request_id(),
                        action=action,
                        entity_id=entity_id,
                        status=status,
                        error_code=error_code,
                        latency_ms=round(latency_ms),
                        ttft_ms=None if ttft_ms is None else round(ttft_ms),
                        created_at=now_iso(),
                    )
                )
        except Exception:
            # Auditing must never break the user's action.
            log.exception("transaction_log_failed", action=action)

    @asynccontextmanager
    async def track(self, action: str, entity_id: str | None = None) -> AsyncIterator[Tracked]:
        """Records the wrapped block as ok, or as an error with its code."""
        tracked = Tracked(entity_id)
        start = time.perf_counter()
        try:
            yield tracked
        except AppError as exc:
            await self._finish(action, tracked, start, "error", exc.code)
            raise
        except Exception:
            await self._finish(action, tracked, start, "error", "internal_error")
            raise
        await self._finish(action, tracked, start, "ok", None)

    async def _finish(
        self, action: str, tracked: Tracked, start: float, status: str, code: str | None
    ) -> None:
        await self.record(
            action,
            status=status,
            latency_ms=(time.perf_counter() - start) * 1000,
            entity_id=tracked.entity_id,
            error_code=code,
        )
