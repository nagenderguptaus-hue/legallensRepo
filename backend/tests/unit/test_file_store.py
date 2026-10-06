import hashlib
from pathlib import Path

import pytest

from legallens.errors import AppError
from legallens.storage.file_store import FileStore


class ChunkedSource:
    """Simulates an upload arriving in chunks, with no trustworthy size up front."""

    def __init__(self, data: bytes, chunk: int = 1000) -> None:
        self._data = data
        self._chunk = chunk
        self.reads = 0

    async def read(self, size: int = -1) -> bytes:
        self.reads += 1
        piece, self._data = self._data[: self._chunk], self._data[self._chunk :]
        return piece


@pytest.fixture
def store(tmp_path: Path) -> FileStore:
    s = FileStore(tmp_path / "uploads", tmp_path / "tmp")
    s.ensure_dirs()
    return s


async def test_receive_hashes_and_commits(store: FileStore) -> None:
    data = b"%PDF-" + b"x" * 5000
    received = await store.receive(ChunkedSource(data), max_bytes=10_000)
    assert received.size == len(data)
    assert received.sha256 == hashlib.sha256(data).hexdigest()

    final = store.commit(received.path, "doc_1", "pdf")
    assert final == store.uploads_dir / "doc_1" / "original.pdf"
    assert final.read_bytes() == data
    assert not received.path.exists()

    store.delete_document("doc_1")
    assert not (store.uploads_dir / "doc_1").exists()


async def test_oversized_upload_stops_early_and_leaves_nothing(store: FileStore) -> None:
    source = ChunkedSource(b"x" * 50_000)
    with pytest.raises(AppError) as info:
        await store.receive(source, max_bytes=3_000)
    assert info.value.code == "file_too_large"
    assert source.reads <= 4  # stopped as soon as the limit was crossed
    assert list(store.tmp_dir.iterdir()) == []


def test_clear_tmp_removes_partial_uploads(store: FileStore) -> None:
    (store.tmp_dir / "upload_x.part").write_bytes(b"partial")
    store.clear_tmp()
    assert list(store.tmp_dir.iterdir()) == []
