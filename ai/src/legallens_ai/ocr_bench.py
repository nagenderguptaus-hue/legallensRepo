"""OCR bake-off (ingestion.todo.md Step 5): which engine and settings read scanned legal pages best.

Pages: the eval documents (``evals/documents``, 23 pages) and dense pages from two CUAD
contracts (the LegalBench-RAG corpus, when downloaded). Each page is drawn as a 300 DPI
grayscale scan in Times New Roman 11 pt, at three qualities, and embedded in a PDF. Every
config then reads it through the production path: PDFium render at the config's DPI → engine →
``layout`` (rows → paragraphs).

Qualities:
- ``clean``: exactly as drawn;
- ``noisy``: rotated 0.8°, slightly blurred, grey paper, Gaussian noise: a so-so office scan;
- ``fax``: down to 100 DPI, black-and-white, back up to 300 DPI, with specks.

Metrics per config and quality:
- ``CER``: character error rate, Levenshtein distance / reference length, on whitespace-
  normalised page text (curly quotes and dashes folded to ASCII, so typography isn't an error);
- ``WER``: the same over words;
- ``para``: share of reference paragraphs recovered exactly (OCR and layout together);
- ``s/page``: render + OCR + layout, on this machine;
- ``conf``: the engine's mean confidence (does it notice its own mistakes?).

``--retrieval`` also indexes the OCR'd eval documents with the real embedder and reranker and
checks, for each answerable Ask eval question, whether a right page is in the top 8: OCR'd text
vs the digital text. Local models only, no API calls.

Needs the ``bench`` dependency group (``uv sync --group bench``) and, for Tesseract configs, the
Tesseract program (``LL_TESSERACT_CMD`` or the default Windows install path).
"""

import asyncio
import io
import json
import os
import random
import statistics
import tempfile
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from legallens_ai.config import AI_ROOT, AISettings
from legallens_ai.ingestion import layout
from legallens_ai.ingestion.ocr import OcrEngine, OcrLine, RapidOcrEngine
from legallens_ai.ingestion.render import PdfRenderer
from legallens_ai.retrieval.chunker import is_heading

BENCH_ROOT = AI_ROOT / "data" / "benchmarks"
RESULTS_DIR = BENCH_ROOT / "results"
CUAD_DIR = BENCH_ROOT / "legalbenchrag" / "corpus" / "cuad"
EVAL_DOCS = AI_ROOT / "evals" / "documents"
QUALITIES = ("clean", "noisy", "fax")

SCAN_DPI = 300
PAGE_PX = (int(8.5 * SCAN_DPI), int(11 * SCAN_DPI))
MARGIN_PX = SCAN_DPI  # 1 inch
FONT_PX = round(11 / 72 * SCAN_DPI)  # 11 pt
LINE_PX = round(FONT_PX * 1.25)
CUAD_PAGES = 4  # dense pages taken from each contract
CUAD_CONTRACTS = 2


# ---------------------------------------------------------------- engines


@dataclass(frozen=True)
class Config:
    name: str
    engine: str  # "rapidocr" | "tesseract"
    dpi: int
    max_side: int = 2000
    model_size: str = "small"
    angle_cls: bool = False


CONFIGS: dict[str, Config] = {
    c.name: c
    for c in (
        Config("rapid-tiny", "rapidocr", 200, model_size="tiny"),
        Config("rapid-tiny-fullres", "rapidocr", 200, max_side=4000, model_size="tiny"),
        Config("rapid-small", "rapidocr", 200),
        Config("rapid-small+cls", "rapidocr", 200, angle_cls=True),
        Config("rapid-small-fullres", "rapidocr", 200, max_side=4000),
        Config("rapid-small-300dpi", "rapidocr", 300, max_side=4000),
        Config("rapid-medium-fullres", "rapidocr", 200, max_side=4000, model_size="medium"),
        Config("tesseract-200dpi", "tesseract", 200),
        Config("tesseract-300dpi", "tesseract", 300),
    )
}


class TesseractEngine:
    """Tesseract 5 through pytesseract (bench only unless it wins). Words are grouped into the
    lines Tesseract itself found; a line's score is its words' mean confidence."""

    name = "tesseract"

    def __init__(self) -> None:
        import pytesseract

        default = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
        cmd = os.environ.get("LL_TESSERACT_CMD") or (str(default) if default.exists() else None)
        if cmd:
            pytesseract.pytesseract.tesseract_cmd = cmd
        self._tess = pytesseract

    async def read(self, image: Any) -> list[OcrLine]:
        def run() -> list[OcrLine]:
            data = self._tess.image_to_data(
                image, lang="eng", config="--psm 3", output_type=self._tess.Output.DICT
            )
            lines: dict[tuple[int, int, int], list[int]] = {}
            for i, word in enumerate(data["text"]):
                if word.strip() and float(data["conf"][i]) >= 0:
                    key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
                    lines.setdefault(key, []).append(i)
            out: list[OcrLine] = []
            for idx in lines.values():
                left = min(data["left"][i] for i in idx)
                top = min(data["top"][i] for i in idx)
                right = max(data["left"][i] + data["width"][i] for i in idx)
                bottom = max(data["top"][i] + data["height"][i] for i in idx)
                text = " ".join(data["text"][i] for i in idx)
                score = statistics.mean(float(data["conf"][i]) for i in idx) / 100
                out.append(OcrLine(text, (left, top, right, bottom), score))
            return out

        return await asyncio.to_thread(run)


def make_engine(config: Config, models_dir: Path) -> OcrEngine:
    if config.engine == "tesseract":
        return TesseractEngine()
    return RapidOcrEngine(
        models_dir,
        model_size=config.model_size,  # type: ignore[arg-type]
        max_side=config.max_side,
        angle_cls=config.angle_cls,
    )


# ---------------------------------------------------------------- test pages


@dataclass(frozen=True)
class BenchPage:
    source: str  # "lease p.3", "cuad <file> p.2"
    document: str | None  # eval document stem, for the retrieval check
    page: int
    paragraphs: list[str]  # what was drawn on this page, one entry per paragraph (piece)


Font = ImageFont.FreeTypeFont | ImageFont.ImageFont


def _fonts() -> tuple[Font, Font]:
    fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    try:
        return (
            ImageFont.truetype(str(fonts / "times.ttf"), FONT_PX),
            ImageFont.truetype(str(fonts / "timesbd.ttf"), FONT_PX),
        )
    except OSError:  # not Windows: Pillow's bundled sans font
        default = ImageFont.load_default(size=FONT_PX)
        return default, default


def _wrap(text: str, font: Font, width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and font.getlength(candidate) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def flow(paragraphs: Sequence[str]) -> list[list[tuple[str, list[str]]]]:
    """Lays paragraphs onto letter pages: per page, (paragraph piece, its wrapped lines)."""
    regular, bold = _fonts()
    width = PAGE_PX[0] - 2 * MARGIN_PX
    bottom = PAGE_PX[1] - MARGIN_PX
    pages: list[list[tuple[str, list[str]]]] = [[]]
    y = MARGIN_PX
    for paragraph in paragraphs:
        lines = _wrap(paragraph, bold if is_heading(paragraph) else regular, width)
        while lines:
            room = max(0, (bottom - y) // LINE_PX)
            if room == 0:
                pages.append([])
                y = MARGIN_PX
                continue
            piece, lines = lines[:room], lines[room:]
            pages[-1].append((" ".join(piece), piece))
            y += len(piece) * LINE_PX + LINE_PX // 2
    return [p for p in pages if p]


def draw(page: list[tuple[str, list[str]]]) -> Image.Image:
    regular, bold = _fonts()
    image = Image.new("L", PAGE_PX, 255)
    pen = ImageDraw.Draw(image)
    y = MARGIN_PX
    for text, lines in page:
        font = bold if is_heading(text) else regular
        for line in lines:
            pen.text((MARGIN_PX, y), line, font=font, fill=0)
            y += LINE_PX
        y += LINE_PX // 2
    return image


def degrade(image: Image.Image, quality: str, rng: random.Random) -> Image.Image:
    if quality == "clean":
        return image
    np_rng = np.random.default_rng(rng.randrange(2**32))
    if quality == "noisy":
        out = image.rotate(0.8, resample=Image.Resampling.BICUBIC, fillcolor=255)
        out = out.filter(ImageFilter.GaussianBlur(0.8))
        pixels = np.asarray(out, dtype=np.float32) * 0.93  # grey paper
        pixels += np_rng.normal(0, 14, pixels.shape)
        return Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8))
    # fax: 100 DPI black-and-white, scaled back up, with specks
    small = image.resize((PAGE_PX[0] // 3, PAGE_PX[1] // 3), Image.Resampling.BILINEAR)
    bw = np.where(np.asarray(small) < 150, 0, 255).astype(np.uint8)
    specks = np_rng.random(bw.shape) < 0.003
    bw[specks] = 255 - bw[specks]
    return Image.fromarray(bw).resize(PAGE_PX, Image.Resampling.NEAREST)


def bench_pages() -> list[BenchPage]:
    pages: list[BenchPage] = []
    for path in sorted(EVAL_DOCS.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for page in data["pages"]:
            laid = flow(page["paragraphs"])
            if len(laid) != 1:
                raise ValueError(f"{path.stem} p.{page['page']} doesn't fit on one page")
            pages.append(
                BenchPage(
                    f"{path.stem} p.{page['page']}",
                    path.stem,
                    page["page"],
                    [text for text, _ in laid[0]],
                )
            )
    if CUAD_DIR.is_dir():
        contracts = [p for p in sorted(CUAD_DIR.glob("*.txt")) if _size(p) > 20_000]
        for path in contracts[:CUAD_CONTRACTS]:
            raw = path.read_text(encoding="utf-8", errors="replace")
            paragraphs = [" ".join(ln.split()) for ln in raw.splitlines() if ln.strip()]
            for number, laid_page in enumerate(flow(paragraphs)[:CUAD_PAGES], start=1):
                pages.append(
                    BenchPage(
                        f"cuad {path.stem[:28]} p.{number}",
                        None,
                        number,
                        [text for text, _ in laid_page],
                    )
                )
    return pages


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:  # some CUAD names exceed Windows' 260-character path limit
        return 0


def scan_pdf(pages: Sequence[BenchPage], quality: str, seed: int = 7) -> bytes:
    """One PDF whose pages are 300 DPI scan images (no text layer)."""
    rng = random.Random(f"{seed}-{quality}")  # noqa: S311 (reproducible noise, not crypto)
    images = [degrade(draw(flow(p.paragraphs)[0]), quality, rng) for p in pages]
    out = io.BytesIO()
    images[0].save(out, "PDF", resolution=SCAN_DPI, save_all=True, append_images=images[1:])
    return out.getvalue()


# ---------------------------------------------------------------- scoring

# Curly quotes, en/em dashes and no-break spaces folded to ASCII.
_FOLD = str.maketrans(
    {chr(0x2018): "'", chr(0x2019): "'", chr(0x201C): '"', chr(0x201D): '"'}
    | {chr(0x2013): "-", chr(0x2014): "-", chr(0x00A0): " "}
)


def normalise(text: str) -> str:
    return " ".join(text.translate(_FOLD).split())


def error_rates(reference: str, hypothesis: str) -> tuple[float, float]:
    from rapidfuzz.distance import Levenshtein

    ref, hyp = normalise(reference), normalise(hypothesis)
    cer = Levenshtein.distance(ref, hyp) / max(1, len(ref))
    ref_words, hyp_words = ref.split(), hyp.split()
    wer = Levenshtein.distance(ref_words, hyp_words) / max(1, len(ref_words))
    return cer, wer


@dataclass
class PageResult:
    config: str
    quality: str
    source: str
    cer: float
    wer: float
    para_exact: float
    confidence: float | None
    seconds: float


@dataclass
class Summary:
    config: str
    quality: str
    pages: int
    cer: float  # mean over pages
    cer_p90: float
    wer: float
    para_exact: float
    confidence: float | None
    seconds_per_page: float
    worst: list[tuple[str, float]] = field(default_factory=list)


def summarise(results: list[PageResult]) -> Summary:
    confidences = [r.confidence for r in results if r.confidence is not None]
    cers = sorted(r.cer for r in results)
    return Summary(
        config=results[0].config,
        quality=results[0].quality,
        pages=len(results),
        cer=statistics.mean(cers),
        cer_p90=cers[int(0.9 * (len(cers) - 1))],
        wer=statistics.mean(r.wer for r in results),
        para_exact=statistics.mean(r.para_exact for r in results),
        confidence=statistics.mean(confidences) if confidences else None,
        seconds_per_page=statistics.mean(r.seconds for r in results),
        worst=[(r.source, round(r.cer, 4)) for r in sorted(results, key=lambda r: -r.cer)[:3]],
    )


# ---------------------------------------------------------------- runs


async def read_pdf(
    pdf: Path, engine: OcrEngine, dpi: int
) -> list[tuple[list[str], float | None, float]]:
    """(paragraphs, confidence, seconds) per page, through the production render + layout."""
    out = []
    with PdfRenderer(pdf) as renderer:
        for index in range(len(renderer)):
            started = time.perf_counter()
            image = await asyncio.to_thread(renderer.render, index, dpi)
            lines = await engine.read(image)
            paragraphs = layout.paragraphs(lines)
            out.append((paragraphs, layout.confidence(lines), time.perf_counter() - started))
    return out


async def run_config(
    config: Config, pages: Sequence[BenchPage], pdfs: dict[str, Path], models_dir: Path
) -> list[PageResult]:
    engine = make_engine(config, models_dir)
    # Warm-up: load the models before timing anything.
    await engine.read(np.full((200, 400), 255, dtype=np.uint8))
    results: list[PageResult] = []
    for quality, pdf in pdfs.items():
        for page, (paragraphs, confidence, seconds) in zip(
            pages, await read_pdf(pdf, engine, config.dpi), strict=True
        ):
            cer, wer = error_rates(" ".join(page.paragraphs), " ".join(paragraphs))
            found = {normalise(p) for p in paragraphs}
            exact = sum(normalise(p) in found for p in page.paragraphs) / len(page.paragraphs)
            results.append(
                PageResult(config.name, quality, page.source, cer, wer, exact, confidence, seconds)
            )
    return results


def report(summaries: list[Summary]) -> str:
    header = (
        f"{'config':<22} {'quality':<6} {'pages':>5} {'CER':>7} {'CER p90':>8} {'WER':>7} "
        f"{'para':>6} {'conf':>6} {'s/page':>7}"
    )
    rows = [header, "-" * len(header)]
    for s in summaries:
        conf = f"{s.confidence:.3f}" if s.confidence is not None else "-"
        rows.append(
            f"{s.config:<22} {s.quality:<6} {s.pages:>5} {s.cer:>7.2%} {s.cer_p90:>8.2%} "
            f"{s.wer:>7.2%} {s.para_exact:>6.0%} {conf:>6} {s.seconds_per_page:>7.2f}"
        )
    return "\n".join(rows)


async def retrieval_check(
    config: Config, quality: str, pdf: Path, pages: Sequence[BenchPage], settings: AISettings
) -> dict[str, Any]:
    """Right page in the top 8 for each answerable Ask eval question: OCR'd vs digital text."""
    from legallens_ai.ingestion import make_ingestor
    from legallens_ai.retrieval import open_retrieval
    from legallens_ai.retrieval.loaders import load_document
    from legallens_ai.workflow_evals import load_ask_cases

    cases = [c for c in load_ask_cases() if c.expected == "answered"]
    hits: dict[str, dict[str, bool]] = {"digital": {}, "ocr": {}}
    with tempfile.TemporaryDirectory() as tmp:
        local = settings.model_copy(update={"data_dir": Path(tmp), "ocr_dpi": config.dpi})
        retrieval = await open_retrieval(local)
        try:
            ingestor = make_ingestor(local, retrieval, ocr=make_engine(config, settings.models_dir))
            names: dict[str, str] = {}
            for stem in sorted({c.document for c in cases}):
                loaded = load_document(EVAL_DOCS / f"{stem}.json")
                names[stem] = loaded.name
                await retrieval.indexer.index(
                    document_id=f"digital-{stem}", name=loaded.name, type="pdf", pages=loaded.pages
                )
                # The OCR'd copy: this document's pages cut out of the bench PDF.
                indexes = [i for i, p in enumerate(pages) if p.document == stem]
                single = Path(tmp) / f"{stem}.pdf"
                _extract_pages(pdf, indexes, single)
                await ingestor.ingest(
                    document_id=f"ocr-{stem}", name=loaded.name, type="pdf", path=single
                )
            for case in cases:
                question = case.question
                for kind in ("digital", "ocr"):
                    result = await retrieval.retriever.retrieve(
                        document_id=f"{kind}-{case.document}",
                        document_name=names[case.document],
                        query=question,
                    )
                    hits[kind][case.id] = bool(
                        {sc.chunk.page for sc in result.chunks} & set(case.pages)
                    )
        finally:
            await retrieval.close()
    return {
        "config": config.name,
        "quality": quality,
        "questions": len(cases),
        "digital_hits": sum(hits["digital"].values()),
        "ocr_hits": sum(hits["ocr"].values()),
        "lost": sorted(k for k, v in hits["digital"].items() if v and not hits["ocr"][k]),
    }


def _extract_pages(pdf: Path, indexes: list[int], out: Path) -> None:
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(pdf)
    writer = PdfWriter()
    for i in indexes:
        writer.add_page(reader.pages[i])
    with out.open("wb") as fh:
        writer.write(fh)


async def run_bench(
    config_names: Sequence[str],
    qualities: Sequence[str],
    *,
    settings: AISettings,
    retrieval: bool = False,
    limit: int | None = None,
) -> Path:
    pages = bench_pages()
    if limit:
        pages = pages[:limit]
    print(f"{len(pages)} pages x {len(qualities)} qualities x {len(config_names)} configs")
    work = Path(tempfile.mkdtemp(prefix="ocr-bench-"))
    pdfs = {}
    for quality in qualities:
        pdfs[quality] = work / f"{quality}.pdf"
        pdfs[quality].write_bytes(scan_pdf(pages, quality))

    summaries: list[Summary] = []
    per_page: list[PageResult] = []
    checks: list[dict[str, Any]] = []
    for name in config_names:
        config = CONFIGS[name]
        print(f"… {name}", flush=True)
        try:
            results = await run_config(config, pages, pdfs, settings.models_dir)
        except Exception as exc:  # e.g. Tesseract missing, model download blocked
            print(f"  skipped: {type(exc).__name__}: {exc}")
            continue
        per_page.extend(results)
        for quality in qualities:
            summaries.append(summarise([r for r in results if r.quality == quality]))
        if retrieval:
            for quality in qualities:
                checks.append(
                    await retrieval_check(config, quality, pdfs[quality], pages, settings)
                )

    print()
    print(report(summaries))
    for check in checks:
        print(
            f"retrieval {check['config']:<22} {check['quality']:<6} right page in top 8: "
            f"digital {check['digital_hits']}/{check['questions']}, "
            f"OCR {check['ocr_hits']}/{check['questions']}"
            + (f"  lost: {', '.join(check['lost'])}" if check["lost"] else "")
        )
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"ocr-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(
        json.dumps(
            {
                "configs": [asdict(CONFIGS[n]) for n in config_names],
                "summaries": [asdict(s) for s in summaries],
                "retrieval": checks,
                "pages": [asdict(r) for r in per_page],
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"\nResults written to {out}")
    return out
