"""The AI-layer ingestion adapter, end to end through the API (``uv sync --extra ai``).

Real PDF rendering, real OCR (RapidOCR's bundled models, no download) and a real embedded
Qdrant; only the embedding model is a fake, so no model download is needed.
"""

import hashlib
import math
import textwrap
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import pytest

pytest.importorskip("legallens_ai", reason="needs the AI layer: uv sync --extra ai")

from fpdf import FPDF
from legallens_ai.config import AISettings
from legallens_ai.retrieval import Retrieval
from legallens_ai.retrieval.chunk_store import ChunkStore
from legallens_ai.retrieval.hybrid import HybridRetriever
from legallens_ai.retrieval.indexer import DocumentIndexer
from legallens_ai.retrieval.vector_store import QdrantVectorStore
from legallens_ai.runtime import AIRuntime
from PIL import Image, ImageDraw, ImageFont

from legallens.adapters.ai_ingestion import AIIngestionPipeline, ai_settings_for
from legallens.config import Settings
from tests.conftest import RunApp
from tests.factories import NDA_PAGES

EXHIBIT = [
    "EXHIBIT A",
    "Either party may terminate this Agreement with thirty (30) days written notice.",
]


class HashEmbedder:
    model_name = "hash"

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * 16
        for word in text.lower().split():
            vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % 16] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    async def dimension(self) -> int:
        return 16

    async def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


class NoReranker:
    model_name = "none"

    async def scores(self, query: str, texts: Sequence[str]) -> list[float]:
        return [0.0] * len(texts)


def scan(paragraphs: list[str]) -> Image.Image:
    """A letter-size page at 200 DPI with the text drawn on it: no text layer."""
    image = Image.new("L", (1700, 2200), 255)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=34)
    y = 200
    for paragraph in paragraphs:
        for line in textwrap.wrap(paragraph, 70):
            draw.text((200, y), line, font=font, fill=0)
            y += 46
        y += 30
    return image


def mixed_pdf(pages: list[list[str] | Image.Image]) -> bytes:
    pdf = FPDF(unit="pt", format="letter")
    pdf.set_font("helvetica", size=11)
    for page in pages:
        pdf.add_page()
        if isinstance(page, Image.Image):
            pdf.image(page, x=0, y=0, w=pdf.w, h=pdf.h)
        else:
            for paragraph in page:
                pdf.multi_cell(0, 14, paragraph, new_x="LMARGIN", new_y="NEXT")
                pdf.ln(8)
    return bytes(pdf.output())


@pytest.fixture
async def pipeline(data_dir: Path) -> AsyncIterator[tuple[AIIngestionPipeline, Retrieval]]:
    ai_dir = data_dir / "ai"
    store = ChunkStore(ai_dir / "chunks.db")
    embedder = HashEmbedder()
    vectors = QdrantVectorStore(collection="test", dimension=16, path=ai_dir / "qdrant")
    reranker = NoReranker()
    retrieval = Retrieval(
        store=store,
        embedder=embedder,
        reranker=reranker,
        vectors=vectors,
        indexer=DocumentIndexer(store, embedder, vectors),
        retriever=HybridRetriever(store, embedder, vectors, reranker),
    )
    # "small" ships inside the package: no model download in tests or CI.
    settings = AISettings(_env_file=None, data_dir=ai_dir, ocr_model_size="small")
    yield AIIngestionPipeline(AIRuntime(settings, retrieval=retrieval)), retrieval


async def test_mixed_pdf_is_ocrd_indexed_and_purged(
    run_app: RunApp, pipeline: tuple[AIIngestionPipeline, Retrieval]
) -> None:
    adapter, retrieval = pipeline
    content = mixed_pdf([NDA_PAGES[0], scan(EXHIBIT)])
    async with run_app(pipeline=adapter) as r:
        doc = await r.ready_document(content, "NDA_with_exhibit.pdf")
        assert doc["isScanned"] is True
        assert doc["warnings"] == []

        digital = (await r.client.get(f"/api/documents/{doc['id']}/pages/1")).json()
        assert (digital["ocr"], digital["ocrConfidence"]) == (False, None)
        scanned = (await r.client.get(f"/api/documents/{doc['id']}/pages/2")).json()
        assert scanned["ocr"] is True and scanned["ocrConfidence"] > 0.9
        assert scanned["paragraphs"] == EXHIBIT

        chunks = await retrieval.store.chunks(doc["id"])
        assert [c.page for c in chunks] == [1, 2]
        vector = await retrieval.embedder.embed_query("terminate notice")
        assert len(await retrieval.vectors.search(doc["id"], vector, 5)) == 2

        assert (await r.client.delete(f"/api/documents/{doc['id']}")).status_code == 204
        assert await retrieval.store.chunks(doc["id"]) == []
        assert await retrieval.vectors.search(doc["id"], vector, 5) == []


async def test_blank_scan_fails_with_the_ai_layers_message(
    run_app: RunApp, pipeline: tuple[AIIngestionPipeline, Retrieval]
) -> None:
    adapter, _ = pipeline
    async with run_app(pipeline=adapter) as r:
        doc = (await r.upload(mixed_pdf([scan([])]), "blank.pdf")).json()
        await r.container.runner.wait_idle()
        failed = (await r.client.get(f"/api/documents/{doc['id']}")).json()
        assert failed["status"] == "failed"
        assert failed["error"].startswith("No text could be found in this document, even with OCR")


def test_ai_index_lives_in_the_backend_data_dir(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path)
    assert ai_settings_for(settings).data_dir == tmp_path.resolve() / "ai"


def test_factory_builds_the_adapter_from_the_setting(tmp_path: Path) -> None:
    from legallens.adapters import load_ingestion_pipeline

    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        ingestion="legallens.adapters.ai_ingestion:create",
    )
    assert isinstance(load_ingestion_pipeline(settings), AIIngestionPipeline)
