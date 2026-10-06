"""Async SQLite engine, session factory and startup migrations."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _set_pragmas(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def sync_url(db_path: Path) -> str:
    return f"sqlite:///{db_path.as_posix()}"


def run_migrations(db_path: Path) -> None:
    """Bring the schema up to date (blocking; call via ``asyncio.to_thread``)."""
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", sync_url(db_path))
    command.upgrade(cfg, "head")


class Database:
    def __init__(self, db_path: Path) -> None:
        self.engine: AsyncEngine = create_async_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
        event.listen(self.engine.sync_engine, "connect", _set_pragmas)
        self._sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """A session in a transaction: commits on success, rolls back on error."""
        async with self._sessions() as session, session.begin():
            yield session

    async def ping(self) -> bool:
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:
            return False
        return True

    async def dispose(self) -> None:
        await self.engine.dispose()
