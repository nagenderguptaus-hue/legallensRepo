from pathlib import Path

import pytest

from legallens_ai.ingestion import DocumentIngestor, IngestionError, Stage
from legallens_ai.ingestion.layout import confidence, page_text, paragraphs
from legallens_ai.ingestion.ocr import OcrLine
from legallens_ai.ingestion.render import PdfRenderer
from legallens_ai.ingestion.text import SectionTracker, meaningful_chars, split_paragraphs
from legallens_ai.retrieval.chunk_store import ChunkStore
from legallens_ai.retrieval.indexer import DocumentIndexer
from tests.ingestion_fakes import ScriptedOcr, line, make_docx, make_pdf, scanned_image
from tests.workflow_fakes import FakeEmbedder, InMemoryVectorStore

TERM = "This Agreement shall remain in effect for three (3) years from the Effective Date."
RENT = "Tenant shall pay monthly Base Rent of $4,500 on the first day of each month."
NOTICE = "Either party may terminate this Agreement with thirty (30) days written notice."


# ---------------------------------------------------------------- text helpers


def test_meaningful_chars_ignores_punctuation_and_space() -> None:
    assert meaningful_chars(" -- 3 -- \n\t. ") == 1
    assert meaningful_chars("Page 12") == 6


def test_split_paragraphs_rebuilds_wrapped_lines() -> None:
    text = (
        "1. Term\n"
        "This Agreement shall remain in effect for a period of three years from\n"
        "the Effective Date.\n"
        "Page 2 of 9\n"
        "The parties may renew in writ-\n"
        "ing.\n"
    )
    assert split_paragraphs(text) == [
        "1. Term",
        "This Agreement shall remain in effect for a period of three years from the "
        "Effective Date.",
        "The parties may renew in writing.",
    ]


def test_section_tracker_carries_the_last_heading_forward() -> None:
    sections = SectionTracker()
    assert sections.page(["1. Term", "2. Rent"]) == "1. Term"
    assert sections.page([]) == "2. Rent"


# ---------------------------------------------------------------- layout


def test_layout_joins_split_boxes_and_wrapped_lines_into_paragraphs() -> None:
    lines = [
        line("Premises", 100, left=260),  # same row as "1.", found as a separate box
        line("1.", 102, left=200),
        line("Landlord leases to Tenant the ground-floor retail unit at 12 Harbor", 160),
        line("Way, Oakland.", 198),  # 8 px gap: same paragraph
        line("Tenant shall keep the premises in good repair and return them", 260),  # 32 px gap
        line("in the same condition.", 298),
    ]
    assert paragraphs(lines) == [
        "1. Premises",
        "Landlord leases to Tenant the ground-floor retail unit at 12 Harbor Way, Oakland.",
        "Tenant shall keep the premises in good repair and return them in the same condition.",
    ]


def test_layout_reads_rows_top_to_bottom_whatever_the_engine_order() -> None:
    lines = [line("second line.", 140), line("First line that is long enough and", 100)]
    assert page_text(lines) == "First line that is long enough and\nsecond line."


def test_layout_repairs_hyphens_and_drops_page_numbers() -> None:
    lines = [
        line("The Receiving Party shall protect the infor-", 100),
        line("mation with reasonable care.", 138),
        line("Page 3 of 9", 2000, left=800),
    ]
    assert paragraphs(lines) == [
        "The Receiving Party shall protect the information with reasonable care."
    ]


def test_full_width_all_caps_clause_lines_are_not_headings() -> None:
    lines = [
        line("10.2 Excluded Damages. NEITHER PARTY SHALL BE LIABLE FOR ANY", 100),
        line("INDIRECT, INCIDENTAL, SPECIAL OR CONSEQUENTIAL DAMAGES OR", 140),
        line("LOST PROFITS.", 180),
    ]
    assert paragraphs(lines) == [
        "10.2 Excluded Damages. NEITHER PARTY SHALL BE LIABLE FOR ANY INDIRECT, INCIDENTAL, "
        "SPECIAL OR CONSEQUENTIAL DAMAGES OR LOST PROFITS."
    ]


def test_one_line_paragraphs_with_uniform_spacing_stay_apart() -> None:
    # Every step is the same, so spacing can't tell lines from paragraphs; the short last
    # line of each sentence does. The long middle line has no full stop: it continues.
    lines = [
        line("4. Termination", 100),
        line("Either party may terminate with thirty (30) days written notice.", 160),
        line("The Receiving Party shall be liable for any breach of this Agreement and", 220),
        line("its affiliates.", 280),
    ]
    assert paragraphs(lines) == [
        "4. Termination",
        "Either party may terminate with thirty (30) days written notice.",
        "The Receiving Party shall be liable for any breach of this Agreement and its affiliates.",
    ]


def test_a_heading_after_a_full_width_sentence_starts_a_new_paragraph() -> None:
    # Uniform spacing, and the sentence row is the widest one: only the full stop tells.
    lines = [
        line("2. Term", 100),
        line("This Agreement shall remain in effect for three years from the Date.", 160),
        line("3. Obligations", 220),
        line("The Receiving Party shall protect it.", 280),
    ]
    assert paragraphs(lines) == [
        "2. Term",
        "This Agreement shall remain in effect for three years from the Date.",
        "3. Obligations",
        "The Receiving Party shall protect it.",
    ]


def test_a_slightly_rotated_scan_keeps_line_steps_at_the_left_edge() -> None:
    # Rotated ~0.8°: long lines rise 18 px across the page, so their boxes are 18 px taller
    # and start higher than their left ends. Steps are measured at the left end.
    def tilted(text: str, left_y: float, width: float) -> OcrLine:
        rise = width * 0.014
        return OcrLine(text, (200, left_y - 15 - rise, 200 + width, left_y + 15), 0.98, left_y)

    lines = [
        tilted("This Agreement is made between Harbor Properties LLC and", 100, 1300),
        tilted("Maple Street Bakery Inc. having its place of business at", 140, 1300),
        tilted("12 Harbor Way.", 180, 250),
        tilted("Tenant shall pay rent monthly in advance without any demand", 240, 1300),
        tilted("or deduction.", 280, 230),
    ]
    assert paragraphs(lines) == [
        "This Agreement is made between Harbor Properties LLC and Maple Street Bakery Inc. "
        "having its place of business at 12 Harbor Way.",
        "Tenant shall pay rent monthly in advance without any demand or deduction.",
    ]


def test_double_spaced_lines_of_one_paragraph_stay_together() -> None:
    lines = [
        line("Plaintiff alleges that Defendant breached the lease by failing to pay", 100),
        line("rent for the months of March and April and by abandoning the premises", 175),
        line("without notice.", 250),
    ]
    assert len(paragraphs(lines)) == 1


@pytest.mark.parametrize(
    ("ocr_text", "expected"),
    [("1.Term", "1. Term"), ("4.2.Notice", "4.2. Notice"), ("1.5 percent", "1.5 percent")],
)
def test_layout_restores_the_space_after_a_clause_number(ocr_text: str, expected: str) -> None:
    assert page_text([line(ocr_text, 100)]) == expected


def test_confidence_weights_by_characters() -> None:
    lines = [OcrLine("a" * 90, (0, 0, 1, 1), 1.0), OcrLine("b" * 10, (0, 2, 1, 3), 0.5)]
    assert confidence(lines) == pytest.approx(0.95)
    assert confidence([]) is None
    assert paragraphs([]) == []


# ---------------------------------------------------------------- pipeline


def _ingestor(tmp_path: Path, ocr: ScriptedOcr, *, fail_index: bool = False) -> DocumentIngestor:
    indexer = DocumentIndexer(
        ChunkStore(tmp_path / "chunks.db"), FakeEmbedder(fail=fail_index), InMemoryVectorStore()
    )
    return DocumentIngestor(indexer, ocr, dpi=72)


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[Stage, int | None, int | None]] = []

    async def __call__(self, stage: Stage, current: int | None, total: int | None) -> None:
        self.events.append((stage, current, total))


def scanned_lines(*texts: str, score: float = 0.97) -> list[OcrLine]:
    return [line(text, 100 + 60 * i, score=score) for i, text in enumerate(texts)]


async def test_digital_pdf_uses_the_loader_and_never_ocr(tmp_path: Path) -> None:
    ocr = ScriptedOcr()
    pdf = make_pdf(tmp_path / "d.pdf", [["1. Term", TERM], ["2. Rent", RENT]])
    out = await _ingestor(tmp_path, ocr).ingest(document_id="d", name="d.pdf", type="pdf", path=pdf)
    assert ocr.images == []
    assert [r.route for r in out.reports] == ["digital", "digital"]
    assert [p.section for p in out.pages] == ["1. Term", "2. Rent"]
    assert out.pages[0].paragraphs == ["1. Term", TERM]
    assert not out.is_scanned and out.warnings == []
    assert not any(p.ocr for p in out.pages)
    assert out.document.chunks == 2


async def test_scanned_pdf_is_ocrd_page_by_page(tmp_path: Path) -> None:
    ocr = ScriptedOcr([scanned_lines("1. Term", TERM), scanned_lines(RENT, score=0.96)])
    pdf = make_pdf(tmp_path / "s.pdf", [scanned_image(), scanned_image()])
    out = await _ingestor(tmp_path, ocr).ingest(document_id="s", name="s.pdf", type="pdf", path=pdf)
    assert len(ocr.images) == 2
    assert ocr.images[0] == (792, 612)  # letter size at 72 DPI, grayscale
    assert [r.route for r in out.reports] == ["ocr", "ocr"]
    assert out.is_scanned
    assert out.pages[0].paragraphs == ["1. Term", TERM]
    assert [p.section for p in out.pages] == ["1. Term", "1. Term"]
    assert [p.ocr for p in out.pages] == [True, True]
    assert [p.ocr_confidence for p in out.pages] == [0.97, 0.96]
    assert out.warnings == []


async def test_mixed_pdf_routes_each_page(tmp_path: Path) -> None:
    ocr = ScriptedOcr([scanned_lines("EXHIBIT A", NOTICE)])
    pdf = make_pdf(tmp_path / "m.pdf", [["1. Term", TERM], scanned_image(), ["2. Rent", RENT]])
    out = await _ingestor(tmp_path, ocr).ingest(document_id="m", name="m.pdf", type="pdf", path=pdf)
    assert [r.route for r in out.reports] == ["digital", "ocr", "digital"]
    assert out.is_scanned
    assert out.pages[1].paragraphs == ["EXHIBIT A", NOTICE]
    assert [p.ocr_confidence for p in out.pages] == [None, 0.97, None]


async def test_a_stamped_page_number_alone_is_not_a_text_layer(tmp_path: Path) -> None:
    ocr = ScriptedOcr([scanned_lines(TERM)])
    pdf = make_pdf(tmp_path / "n.pdf", [["Page 3 ABC0001"]])  # 11 letters/digits < 20
    out = await _ingestor(tmp_path, ocr).ingest(document_id="n", name="n.pdf", type="pdf", path=pdf)
    assert [r.route for r in out.reports] == ["ocr"]
    assert out.pages[0].paragraphs == [TERM]


async def test_progress_reports_every_stage_in_order(tmp_path: Path) -> None:
    ocr = ScriptedOcr([scanned_lines(NOTICE)])
    pdf = make_pdf(tmp_path / "p.pdf", [["1. Term", TERM], scanned_image()])
    progress = Recorder()
    await _ingestor(tmp_path, ocr).ingest(
        document_id="p", name="p.pdf", type="pdf", path=pdf, progress=progress
    )
    stages = [stage for stage, _, _ in progress.events]
    assert stages[:5] == ["validating", "extracting", "ocr", "quality_check", "chunking"]
    assert set(stages[5:]) == {"indexing"}
    assert progress.events[1:3] == [("extracting", 1, 2), ("ocr", 2, 2)]


async def test_blank_and_low_confidence_pages_get_warnings(tmp_path: Path) -> None:
    ocr = ScriptedOcr([scanned_lines(TERM), [], scanned_lines(RENT, score=0.6)])
    pdf = make_pdf(tmp_path / "w.pdf", [scanned_image()] * 3)
    out = await _ingestor(tmp_path, ocr).ingest(document_id="w", name="w.pdf", type="pdf", path=pdf)
    assert out.warnings == [
        "No text found on page 2 (blank or unreadable). These pages can't be searched or cited.",
        "Low OCR confidence on page 3. Check quotes from these pages against the original.",
    ]
    assert out.pages[1].paragraphs == [] and out.pages[1].ocr_confidence is None


async def test_a_document_with_no_text_at_all_fails(tmp_path: Path) -> None:
    pdf = make_pdf(tmp_path / "b.pdf", [scanned_image(), scanned_image()])
    with pytest.raises(IngestionError) as info:
        await _ingestor(tmp_path, ScriptedOcr()).ingest(
            document_id="b", name="b.pdf", type="pdf", path=pdf
        )
    assert info.value.code == "no_text" and not info.value.retryable


async def test_corrupted_file_is_not_retried(tmp_path: Path) -> None:
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.7 this is not really a pdf")
    with pytest.raises(IngestionError) as info:
        await _ingestor(tmp_path, ScriptedOcr()).ingest(
            document_id="x", name="bad.pdf", type="pdf", path=bad
        )
    assert info.value.code == "unreadable_file" and not info.value.retryable


@pytest.mark.parametrize(
    ("error", "code", "retryable"),
    [
        (RuntimeError("onnx session crashed"), "ocr_failed", True),
        (ImportError("no module named rapidocr"), "ocr_unavailable", False),
    ],
)
async def test_ocr_failures_say_whether_a_retry_can_help(
    tmp_path: Path, error: Exception, code: str, retryable: bool
) -> None:
    pdf = make_pdf(tmp_path / "e.pdf", [scanned_image()])
    with pytest.raises(IngestionError) as info:
        await _ingestor(tmp_path, ScriptedOcr(error=error)).ingest(
            document_id="e", name="e.pdf", type="pdf", path=pdf
        )
    assert (info.value.code, info.value.retryable) == (code, retryable)


async def test_index_failure_is_retryable(tmp_path: Path) -> None:
    pdf = make_pdf(tmp_path / "i.pdf", [["1. Term", TERM]])
    with pytest.raises(IngestionError) as info:
        await _ingestor(tmp_path, ScriptedOcr(), fail_index=True).ingest(
            document_id="i", name="i.pdf", type="pdf", path=pdf
        )
    assert info.value.code == "index_unavailable" and info.value.retryable


async def test_docx_keeps_page_breaks_heading_styles_and_tables(tmp_path: Path) -> None:
    ocr = ScriptedOcr()
    path = make_docx(
        tmp_path / "n.docx",
        [["# Definitions", TERM], ["# Payment", RENT]],
        table=[["Fee", "Amount"], ["Base Rent", "$4,500"]],
    )
    out = await _ingestor(tmp_path, ocr).ingest(
        document_id="n", name="n.docx", type="docx", path=path
    )
    assert ocr.images == []
    assert [p.section for p in out.pages] == ["Definitions", "Payment"]
    assert out.pages[1].paragraphs == ["Payment", RENT, "Fee | Amount", "Base Rent | $4,500"]
    assert not out.is_scanned


async def test_empty_docx_fails_with_its_own_message(tmp_path: Path) -> None:
    path = make_docx(tmp_path / "e.docx", [[]])
    with pytest.raises(IngestionError) as info:
        await _ingestor(tmp_path, ScriptedOcr()).ingest(
            document_id="e", name="e.docx", type="docx", path=path
        )
    assert info.value.message == "This Word file contains no text."


async def test_reingesting_replaces_and_purge_removes_chunks_and_vectors(tmp_path: Path) -> None:
    store = ChunkStore(tmp_path / "chunks.db")
    vectors = InMemoryVectorStore()
    ingestor = DocumentIngestor(DocumentIndexer(store, FakeEmbedder(), vectors), ScriptedOcr())
    pdf = make_pdf(tmp_path / "r.pdf", [["1. Term", TERM], ["2. Rent", RENT]])
    for _ in range(2):
        await ingestor.ingest(document_id="r", name="r.pdf", type="pdf", path=pdf)
    assert len(await store.chunks("r")) == 2 and len(vectors.points) == 2
    await ingestor.purge("r")
    assert await store.chunks("r") == [] and vectors.points == {}
    await ingestor.purge("never-indexed")  # safe for unknown ids


# ---------------------------------------------------------------- real rendering and OCR


def test_renderer_honours_dpi(tmp_path: Path) -> None:
    pdf = make_pdf(tmp_path / "r.pdf", [scanned_image()])
    with PdfRenderer(pdf) as renderer:
        assert len(renderer) == 1
        image = renderer.render(0, 144)
    assert image.shape == (1584, 1224) and image.dtype.name == "uint8"


@pytest.mark.ocr
async def test_rapidocr_reads_a_rendered_scan_end_to_end(tmp_path: Path) -> None:
    from legallens_ai.ingestion.ocr import RapidOcrEngine

    text = ["1. Term", TERM, "2. Termination", NOTICE]
    pdf = make_pdf(tmp_path / "scan.pdf", [scanned_image(text)])
    indexer = DocumentIndexer(
        ChunkStore(tmp_path / "chunks.db"), FakeEmbedder(), InMemoryVectorStore()
    )
    ingestor = DocumentIngestor(indexer, RapidOcrEngine(tmp_path / "models"), dpi=200)
    out = await ingestor.ingest(document_id="scan", name="scan.pdf", type="pdf", path=pdf)
    page = out.pages[0]
    assert page.ocr and page.ocr_confidence is not None and page.ocr_confidence > 0.9
    assert page.paragraphs == text
    assert page.section == "1. Term"
