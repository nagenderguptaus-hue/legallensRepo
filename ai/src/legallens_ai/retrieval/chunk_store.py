"""SQLite chunk store: the canonical chunk text plus the BM25 keyword index (W15, W21c).

Tables: ``documents`` (one row per indexed document), ``chunks`` (text and metadata, in reading
order) and ``chunks_fts`` (an FTS5 index over chunk text and section, kept in sync by triggers).
Keyword search ranks with FTS5's built-in ``bm25()``.

The lawyer's question never reaches FTS5's query language directly: it is reduced to plain
word tokens, each quoted, joined with OR (see ``fts_query``), so characters like ``"``, ``*``,
``NEAR`` or ``:`` can't change the query's meaning or make it fail.

Each call opens its own short-lived connection in a worker thread, so the store is safe to use
from asyncio code and from several tasks at once.
"""

import asyncio
import json
import re
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from legallens_ai.retrieval.types import Chunk, IndexedDocument

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    pages INTEGER NOT NULL,
    chunks INTEGER NOT NULL,
    words INTEGER NOT NULL,
    indexed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    rowid INTEGER PRIMARY KEY,
    chunk_id TEXT NOT NULL UNIQUE,
    document_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    page INTEGER NOT NULL,
    section TEXT,
    paragraphs TEXT NOT NULL,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_by_document ON chunks (document_id, ordinal);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text, section, content='chunks', content_rowid='rowid', tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts (rowid, text, section) VALUES (new.rowid, new.text, new.section);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts (chunks_fts, rowid, text, section)
    VALUES ('delete', old.rowid, old.text, old.section);
END;
"""

# Words too common to say anything about which chunk is relevant.
STOPWORDS = frozenset(
    """a an and any are as at be been but by can could did do does for from had has have how i
    if in into is it its may me might my no not of on or our shall should so such than that
    the their them then there these they this those to under upon was we were what when
    where which who whom why will with would you your about there's what's it's doesn't
    """.split()  # noqa: SIM905 (a word list reads better than 70 quoted strings)
)
_TOKEN = re.compile(r"[^\W_]+(?:['’][^\W_]+)?")


def fts_query(question: str) -> str | None:
    """Plain, quoted OR-query for FTS5, or None when nothing searchable is left."""
    seen: dict[str, None] = {}
    for token in _TOKEN.findall(question.lower()):
        token = token.replace("’", "'")
        if token not in STOPWORDS and (len(token) > 1 or token.isdigit()):
            seen.setdefault(token.replace('"', ""), None)
    if not seen:
        return None
    return " OR ".join(f'"{t}"' for t in seen)


def _row_to_chunk(row: sqlite3.Row) -> Chunk:
    return Chunk(
        chunk_id=row["chunk_id"],
        document_id=row["document_id"],
        ordinal=row["ordinal"],
        page=row["page"],
        section=row["section"],
        paragraphs=tuple(json.loads(row["paragraphs"])),
    )


def _row_to_document(row: sqlite3.Row) -> IndexedDocument:
    return IndexedDocument(
        id=row["id"],
        name=row["name"],
        type=cast(Literal["pdf", "docx"], row["type"]),
        pages=row["pages"],
        chunks=row["chunks"],
        words=row["words"],
        indexed_at=row["indexed_at"],
    )


class ChunkStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._ready = False

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if not self._ready:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            if not self._ready:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.executescript(_SCHEMA)
                self._ready = True
            with conn:  # one transaction per call
                yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------ writes

    def _replace(
        self,
        *,
        document_id: str,
        name: str,
        type: Literal["pdf", "docx"],
        pages: int,
        chunks: Sequence[Chunk],
    ) -> IndexedDocument:
        document = IndexedDocument(
            id=document_id,
            name=name,
            type=type,
            pages=pages,
            chunks=len(chunks),
            words=sum(c.words for c in chunks),
            indexed_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        with self._connect() as conn:
            conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
            conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
            conn.executemany(
                "INSERT INTO chunks (chunk_id, document_id, ordinal, page, section, paragraphs,"
                " text) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        c.chunk_id,
                        c.document_id,
                        c.ordinal,
                        c.page,
                        c.section,
                        json.dumps(list(c.paragraphs), ensure_ascii=False),
                        c.text,
                    )
                    for c in chunks
                ],
            )
            conn.execute(
                "INSERT INTO documents (id, name, type, pages, chunks, words, indexed_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    document.id,
                    document.name,
                    document.type,
                    document.pages,
                    document.chunks,
                    document.words,
                    document.indexed_at,
                ),
            )
        return document

    async def replace_document(
        self,
        *,
        document_id: str,
        name: str,
        type: Literal["pdf", "docx"],
        pages: int,
        chunks: Sequence[Chunk],
    ) -> IndexedDocument:
        """Stores a document's chunks, replacing any earlier version, in one transaction."""
        return await asyncio.to_thread(
            lambda: self._replace(
                document_id=document_id, name=name, type=type, pages=pages, chunks=chunks
            )
        )

    def _delete(self, document_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
            conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))

    async def delete_document(self, document_id: str) -> None:
        await asyncio.to_thread(self._delete, document_id)

    # ------------------------------------------------------------ reads

    def _document(self, document_id: str) -> IndexedDocument | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        return _row_to_document(row) if row else None

    async def document(self, document_id: str) -> IndexedDocument | None:
        return await asyncio.to_thread(self._document, document_id)

    def _documents(self) -> list[IndexedDocument]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM documents ORDER BY indexed_at DESC").fetchall()
        return [_row_to_document(r) for r in rows]

    async def documents(self) -> list[IndexedDocument]:
        return await asyncio.to_thread(self._documents)

    def _chunks(self, document_id: str) -> list[Chunk]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM chunks WHERE document_id = ? ORDER BY ordinal", (document_id,)
            ).fetchall()
        return [_row_to_chunk(r) for r in rows]

    async def chunks(self, document_id: str) -> list[Chunk]:
        """All of a document's chunks, in reading order."""
        return await asyncio.to_thread(self._chunks, document_id)

    def _get(self, chunk_ids: Sequence[str]) -> dict[str, Chunk]:
        if not chunk_ids:
            return {}
        marks = ",".join("?" * len(chunk_ids))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM chunks WHERE chunk_id IN ({marks})",  # noqa: S608 (only "?" marks)
                list(chunk_ids),
            ).fetchall()
        return {r["chunk_id"]: _row_to_chunk(r) for r in rows}

    async def get(self, chunk_ids: Sequence[str]) -> dict[str, Chunk]:
        return await asyncio.to_thread(self._get, chunk_ids)

    def _keyword_search(self, document_id: str, question: str, k: int) -> list[str]:
        query = fts_query(question)
        if query is None:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT c.chunk_id FROM chunks_fts JOIN chunks c ON c.rowid = chunks_fts.rowid"
                " WHERE chunks_fts MATCH ? AND c.document_id = ?"
                " ORDER BY bm25(chunks_fts) LIMIT ?",
                (query, document_id, k),
            ).fetchall()
        return [r["chunk_id"] for r in rows]

    async def keyword_search(self, document_id: str, question: str, k: int) -> list[str]:
        """Chunk ids of the document's best BM25 matches, best first."""
        return await asyncio.to_thread(self._keyword_search, document_id, question, k)
