"""Local file store: ``{data}/uploads/{doc_id}/original.{pdf|docx}``.

File names on disk are built only from server-generated ids, never from the user's file name.
"""

import asyncio
import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

from legallens.errors import AppError
from legallens.ids import new_id

CHUNK_BYTES = 1024 * 1024


class AsyncReadable(Protocol):
    async def read(self, size: int = -1) -> bytes: ...


@dataclass(frozen=True)
class ReceivedFile:
    path: Path
    size: int
    sha256: str


class FileStore:
    def __init__(self, uploads_dir: Path, tmp_dir: Path) -> None:
        self.uploads_dir = uploads_dir
        self.tmp_dir = tmp_dir

    def ensure_dirs(self) -> None:
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

    def clear_tmp(self) -> None:
        """Remove partial uploads left by a crash."""
        for leftover in self.tmp_dir.glob("*.part"):
            leftover.unlink(missing_ok=True)

    def path_for(self, document_id: str, file_type: str) -> Path:
        return self.uploads_dir / document_id / f"original.{file_type}"

    async def receive(self, source: AsyncReadable, max_bytes: int) -> ReceivedFile:
        """Streams an upload to a temp file, hashing as it goes. Stops as soon as the file
        exceeds ``max_bytes``, so an oversized upload never fills the disk."""
        tmp = self.tmp_dir / f"{new_id('upload')}.part"
        digest = hashlib.sha256()
        size = 0
        handle: BinaryIO = await asyncio.to_thread(tmp.open, "wb")
        try:
            while chunk := await source.read(CHUNK_BYTES):
                size += len(chunk)
                if size > max_bytes:
                    raise AppError(
                        413,
                        "file_too_large",
                        f"Files must be {max_bytes // (1024 * 1024)} MB or smaller.",
                    )
                digest.update(chunk)
                await asyncio.to_thread(handle.write, chunk)
        except BaseException:
            await asyncio.to_thread(handle.close)
            tmp.unlink(missing_ok=True)
            raise
        await asyncio.to_thread(handle.close)
        return ReceivedFile(path=tmp, size=size, sha256=digest.hexdigest())

    def commit(self, tmp_path: Path, document_id: str, file_type: str) -> Path:
        """Moves a received temp file to its permanent place (atomic on the same volume)."""
        target = self.path_for(document_id, file_type)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.replace(target)
        return target

    @staticmethod
    def discard(path: Path) -> None:
        path.unlink(missing_ok=True)

    def delete_document(self, document_id: str) -> None:
        shutil.rmtree(self.uploads_dir / document_id, ignore_errors=True)
