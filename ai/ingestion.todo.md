# AI layer — Phase 3c: Ingestion pipeline (loader / OCR → chunk → embed → store)

> **Status:** ✅ implemented 2026-10-14 on branch `ingestion` (all §3 recommendations accepted). Measured results in §6, deviations from this plan in §7, known gaps in §8. **Not committed.**
> **Builds on:** [workflows.todo.md](workflows.todo.md) (chunker, embedder, Qdrant + FTS5 indexer: done) ·
> backend port [ports/ingestion.py](../backend/src/legallens/ports/ingestion.py) ·
> BRD FR-1, FR-3, FR-5, NFR-1, NFR-4, NFR-8.

## 1. What you asked for, and what already exists

Your two paths, when a document is uploaded:

```
scanned page   →  OCR     ─┐
                           ├→  chunk  →  embed  →  store in vector DB (+ BM25 index)
digital page   →  loader  ─┘
```

| Step | Status today | This phase |
|------|--------------|------------|
| Upload → background job → progress shown in the UI | ✅ backend `IngestionRunner` + frontend `IngestionProgress` (already has an "OCR · page n of N" label) | reuse as is |
| Loader (digital PDF / DOCX text) | ✅ backend stand-in (pypdf + python-docx: tables, page breaks, sections). ⚠️ the copy in `ai/retrieval/loaders.py` is a cruder dev-only version | move the backend's tested extractor into `ai/` as the one loader |
| Detect scanned pages | ⚠️ stand-in only notices "no text" and **fails** the document | **new** |
| OCR | ❌ none | **new** |
| Chunk → embed → store | ✅ `DocumentIndexer` (paragraph chunks, bge-base, Qdrant + SQLite FTS5) | reuse unchanged |
| Delete removes chunks + vectors (FR-5) | ✅ `DocumentIndexer.purge` | wire to the backend's `purge` |
| Runs on upload in the real app | ❌ the backend still uses the stand-in (`LL_INGESTION=standin`) | **new**: adapter behind `LL_INGESTION` |

So the real work is: **detection, OCR, one shared loader, and the backend adapter.** No Claude
calls anywhere in ingestion, so this phase has **no API cost**, and document text and images
never leave the machine (NFR-4 holds for ingestion, unlike chat).

## 2. Decisions (please review)

| # | Decision | Why | Alternative |
|---|----------|-----|-------------|
| I1 | **Route per page, not per document.** Each PDF page is checked for a text layer: has one → loader, none → OCR. A document is "scanned" if any page needed OCR. | Legal PDFs are often mixed: a digital contract with a scanned signature page or exhibit. Per-document routing would either OCR good text (slower, worse) or skip the scanned pages. BRD FR-3 also says "check each page". | Per document (Q1 b). |
| I2 | **Text-layer test:** a page is digital if pypdf extracts **≥ 20 letters/digits** from it; otherwise it is OCR'd. Threshold tuned in Step 5. | A scanned page often still has a stamped page number or Bates number ("Page 3", "ABC000123"), so "any text" is the wrong test. | Detect full-page images (more code, misses odd scanner output). |
| I3 | **DOCX always goes through the loader.** Images inside a Word file are not OCR'd. | Word files carry real text; a pasted-in image of a scan is rare. Logged as a known gap. | OCR embedded DOCX images. |
| I4 | **Loader = the backend stand-in's extractor, moved into `ai/ingestion/`** (with its tests). The dev loader in `retrieval/loaders.py` is replaced by it, so the CLI and the app share one code path. | It is already tested against real files: tables in reading order, Word page breaks, hyphen repair, page-number removal, section tracking. LangChain's `PyPDFLoader` / `Docx2txtLoader` would lose tables, pages (DOCX) and sections, and add `langchain-community`. | LangChain community loaders. |
| I5 | **OCR engine behind an `OcrEngine` interface** (NFR-7). Candidate default: **RapidOCR** (PaddleOCR models on ONNX Runtime: pip install only, CPU, same runtime family as our fastembed models). Final pick by a small bake-off against **Tesseract** (Q2). | RapidOCR needs no system install, so it works the same on Windows, Linux CI and Docker (your portability goal). Tesseract is the standard baseline but is a system binary to install on every machine. Measuring both on our own pages beats guessing. | Tesseract only; docTR / PaddleOCR (pull in PyTorch / Paddle, ~1-2 GB). Claude vision OCR: rejected (sends documents off-machine, costs per page). |
| I6 | **Render pages with `pypdfium2`** at **200 DPI, grayscale**, one page at a time (DPI tuned in Step 5: 200 vs 300). | pip-only (Apache/BSD), fast. One page in memory at a time keeps a 300-page scan within laptop RAM. PyMuPDF rejected: AGPL licence. | 300 DPI (slower, sometimes more accurate on small print). |
| I7 | **Layout from OCR boxes:** lines sorted top → bottom, left → right; a new paragraph starts at a vertical gap > ~1.2× the median line height; headings found by the same `is_heading` rule the chunker uses, so sections and citations work on OCR'd pages exactly as on digital ones. | The chunker keeps paragraphs whole; OCR returns lines, so paragraphs have to be rebuilt or chunks would cut clauses. | — |
| I8 | ⚠️ **Single-column pages only.** Two-column layouts are read line by line across columns. | Keeps this phase small; legal contracts and filings are mostly single-column. **Deviation from BRD FR-3 "layout detection"**, recorded as a known gap. | Basic column detection now (Q6 b). |
| I9 | **Quality check:** each OCR'd page stores `ocr=True` and `ocr_confidence` (character-weighted mean of line scores). Pages below **0.80** (tuned in Step 5) get a document warning ("Low OCR confidence on pages 3, 7: check quotes against the original"). An OCR'd page with no text gets a warning; a document with no text at all fails with a clear message. | The backend and frontend already show `warnings`, `isScanned` and the per-page OCR badge; this fills them with real values. | — |
| I10 | **Chunk → embed → store is unchanged** (`DocumentIndexer`: ~300-word paragraph chunks on one page, bge-base, Qdrant embedded + FTS5). OCR'd pages are indexed the same way. | Already measured and tuned in Phase 3b.1; mixing in a second chunking scheme would split the eval. | — |
| I11 | **Errors:** unreadable / corrupted file → `IngestionFailed` (not retried). Index or vector-store failure → `IngestionFailed(retryable=True)` (the runner retries with backoff). OCR model can't load → not retried, message says so. | Matches the runner's existing retry contract (NFR-8). | — |
| I12 | **Concurrency:** one document at a time (the existing runner), pages OCR'd one after another. Parallel page OCR only if Step 5 shows a real speed-up. | ONNX Runtime already uses all CPU cores per page, and embedded Qdrant locks its folder to one writer. | Parallel pages by default. |
| I13 | **Logs:** document id, page counts, routes (digital/OCR), confidences, timings. Never text or images (NFR-5). | Same rule as the rest of the AI layer. | — |
| I14 | **Wiring:** the backend loads the pipeline through its existing setting, `LL_INGESTION=legallens.adapters.ai_ingestion:create`. `legallens-ai` becomes an **optional** backend dependency (`uv sync --extra ai`, path source `../ai`). The stand-in stays the default, so backend tests, CI and the e2e suite are unaffected. | NFR-7: no backend code changes beyond one thin adapter; the AI layer can still be developed and tested on its own. | Keep it in `ai/` only (Q3 b). |
| I15 | **One `Retrieval` per process,** created by the adapter and shared later by the AI orchestrator. Its data goes under the backend's data folder (`<LL_DATA_DIR>/ai/`) unless `LL_AI_DATA_DIR` is set; downloaded models stay in the shared `models_dir`. | Embedded Qdrant locks its folder (known gap in workflows.todo.md §8). Keeping index data next to the backend's DB means one Docker volume and one "reset" covers everything. | — |
| I16 | **Timeout:** raise `LL_INGESTION_TIMEOUT_S` default from 600 s to **1800 s**. | 300 pages (the upload limit) of OCR at ~2 s/page is ~10 min before embedding; 600 s would kill legitimate large scans. Step 5 measures the real s/page. | Keep 600 s and refuse scans over N pages (Q5 b). |

## 3. Open questions (recommended option first)

| # | Question | Options |
|---|----------|---------|
| Q1 ✅ a | Route scanned vs digital **per page** or per document? | **a) Per page** (I1) · b) Per document |
| Q2 ✅ a | How do we pick the OCR engine? | **a) Small bake-off, RapidOCR vs Tesseract** (I'll install Tesseract with winget for the test), pick by accuracy then speed · b) RapidOCR, no bake-off · c) Tesseract |
| Q3 ✅ a | Wire it into the backend's upload flow in this phase? | **a) Yes, behind `LL_INGESTION`** (stand-in stays default) · b) Build and test in `ai/` only, wire later |
| Q4 ✅ a | Where does the thin backend adapter live? | **a) `backend/src/legallens/adapters/ai_ingestion.py`**, next to the stand-ins; `ai/` never imports the backend · b) In `ai/`, importing the backend's port types |
| Q5 ✅ a | Large scans vs the job timeout? | **a) Default timeout 1800 s** (I16) · b) Keep 600 s, cap OCR at N pages with a clear message |
| Q6 ✅ a | Two-column pages? | **a) Defer, record as known gap** (I8) · b) Basic column detection now (+~1 day) |

## 4. Plan

New code lives in `ai/src/legallens_ai/ingestion/`. Work happens on a new git branch
`ingestion` off `integration` (your uncommitted `README.md` change is left alone).

### Step 0 · Spike (½ hour)
- [x] Add `pypdfium2` and `rapidocr` (+ `onnxruntime`) to `ai/`; OCR one generated page; confirm boxes, per-line scores, model download location (must go to `models_dir`, NFR-4) and s/page on this laptop
- [x] If Q2 a: install Tesseract (winget), same check via `pytesseract`

### Step 1 · Loader (digital pages)
- [x] `ingestion/digital.py`: the backend stand-in's PDF + DOCX extraction, moved over with its tests (`text.py` helpers it needs come along)
- [x] Per-page text-layer test (I2)
- [x] `retrieval/loaders.py` → uses the new loader; CLI `index` behaves as before on the eval fixtures

### Step 2 · OCR (scanned pages)
- [x] `ingestion/render.py`: page → grayscale image via pypdfium2 (I6)
- [x] `ingestion/ocr.py`: `OcrEngine` protocol → `OcrLine(text, box, score)`; `RapidOcrEngine` (lazy model load, worker thread, like `models.py`); `TesseractEngine` only if it wins the bake-off
- [x] `ingestion/layout.py`: lines → paragraphs → sections (I7)

### Step 3 · Pipeline
- [x] `ingestion/pipeline.py`: `IngestionPipeline.run(item, progress)`:
  validating → per page: `extracting n/N` or `ocr n/N` → `quality_check` → `chunking` → `indexing`
  (`DocumentIndexer.index`) → returns pages, `is_scanned`, `warnings`
- [x] `purge(document_id)` → `DocumentIndexer.purge`
- [x] Error mapping (I11); settings in `AISettings`: `ocr_engine`, `ocr_dpi`, `ocr_min_text_chars`, `ocr_low_confidence`
- [x] CLI: `legallens-ai index --pages <file>` prints per-page route, confidence, chunk count, timings (§7: no separate `ingest` command)

### Step 4 · Tests (no network, no cost)
- [x] Unit: text-layer test; layout rebuild from fake boxes (wrapped lines, gaps, headings, page numbers); pipeline with a **fake OCR engine**: digital, all-scanned, mixed, blank, low-confidence, index failure → retryable, progress events in order, purge
- [x] Real-OCR tests (marked `ocr`, run locally and in CI): synthetic scanned PDFs generated in code (Pillow renders text → image → PDF, no binaries committed), checked against ground truth
- [x] Ported loader tests pass unchanged

### Step 5 · Measure and tune (evidence for the decisions)
- [x] OCR eval: render the 3 eval documents (`evals/documents/*.json`) as scans at 3 quality levels (clean, noisy + slight skew, low-res fax-like) → **character error rate** and **s/page** per engine and DPI → fills Q2, I6
- [x] Retrieval on OCR'd text: index the scanned versions and rerun the retrieval half of the Ask eval (right page in top 8; no LLM calls, $0) vs the digital baseline
- [x] Tune I2 (text-layer threshold) and I9 (confidence warning threshold) from those runs
- [x] NFR-1 check: 50-page scan Ready in ≤ 5 min, 50-page digital ≤ 90 s, on this laptop
- [x] Results table + any deviations written back into this file

### Step 6 · Backend wiring (if Q3 a)
- [x] `backend/src/legallens/adapters/ai_ingestion.py`: `create(settings)` builds the shared `Retrieval` (I15) and the pipeline; maps AI-layer page/error types onto the backend port's `PageText` / `IngestionResult` / `IngestionFailed`
- [x] Backend `pyproject.toml`: optional extra `ai` → path dependency on `../ai`; default timeout 1800 s (I16); `.env.example` documents `LL_INGESTION`
- [x] Backend integration test with the AI pipeline (skipped when the `ai` extra isn't installed): upload a synthetic scanned PDF → Ready, `isScanned`, OCR pages with confidence → delete → chunks and vectors gone
- [ ] Manual check in the running app (browser): **not done**. The same flow is covered through the HTTP API by `backend/tests/integration/test_ai_ingestion.py` (mixed PDF → Ready, OCR page + confidence, delete purges chunks and vectors; blank scan → Failed).
- [x] Dockerfile / Compose: build context is the repo root, `LL_EXTRAS=ai` build arg, models download into `/data/models`. ⚠️ **Docker build unverified locally** (no Docker on this laptop). The Dockerfile's `uv sync` steps were dry-run on the same layout; CI builds both images (with and without `ai`).

### Step 7 · Docs
- [x] `ai/README.md`: ingestion section (paths, settings, CLI). Backend README: how to switch `LL_INGESTION` to the AI pipeline
- [x] Known gaps in this file and `workflows.todo.md` §8 updated

## 5. Not in this phase

- Wiring the AI **orchestrator** (Ask/Summary/Draft) into the backend's chat: chat keeps the
  stand-in orchestrator, which reads the page text this pipeline returns, so OCR'd documents
  become usable in chat right away; Claude-backed answers come with the orchestrator wiring
- Multi-column layout (if Q6 a), table structure inside scans, handwriting, rotated pages beyond what the engine handles itself
- Re-OCR of PDFs that already carry a poor "searchable PDF" text layer from the scanner (they count as digital)
- Parent/child chunks (BRD §3 step 1): still deferred, as in workflows.todo.md

---

## 6. Measured results (Step 5, 2026-10-14)

**Set-up.** 31 pages: the 23 eval-document pages plus 8 dense pages from two real CUAD contracts
(LegalBench-RAG corpus), each drawn as a 300 DPI scan in Times New Roman 11 pt at three
qualities, then read through the production path (PDFium render → engine → layout).
`clean` = as drawn; `noisy` = rotated 0.8°, blurred, grey paper, Gaussian noise; `fax` =
100 DPI black-and-white with specks. Tool: `legallens-ai bench-ocr` ([ocr_bench.py](src/legallens_ai/ocr_bench.py));
raw results in `data/benchmarks/results/ocr-*.json`. CER = character error rate on
whitespace-normalised text. Speeds are on this laptop (10 cores, CPU only).

| Config | clean CER | noisy CER | fax CER | s/page (quiet CPU) | Notes |
|---|---|---|---|---|---|
| RapidOCR small (bundled), 200 DPI | 0.03% | 0.02% | **3.8%** | 6.5–20 | most accurate; too slow for NFR-1 |
| RapidOCR small + angle classifier | 1.3% | 1.8% | 5.1% | — | the classifier flips upright lines: **off** |
| **RapidOCR tiny, 200 DPI (chosen)** | 0.05% | 0.04% | 7.2% | **1.9–2.6** | |
| Tesseract 5.4, 200 DPI | 0.02% | 0.02% | 11.5% | 1.3–1.6 | system binary |
| Tesseract 5.4, 300 DPI | 0.01% | 0.02% | 11.2% | 1.4–4.0 | no gain over 200 DPI |

- **Engine (Q2, I5): RapidOCR "tiny".** Clean and noisy scans are a tie (all ≤ 0.05% CER).
  On fax-quality scans tiny makes ~40% fewer errors than Tesseract; "small" halves them again
  but takes 7–20 s/page, so a 50-page scan would take 5–16 min (NFR-1: ≤ 5 min). Tiny reads
  50 pages in ≈ 2 min, and it needs no system install (Tesseract would, on every machine and
  image). "small" stays one setting away: `LL_AI_OCR_MODEL_SIZE=small` (then set
  `LL_AI_OCR_LOW_CONFIDENCE≈0.98`).
- **Retrieval on OCR'd text (tiny):** the right page was in the top 8 for **25/25** answerable
  Ask questions at every quality, fax included, the same as on the digital text. The ~7% fax
  CER doesn't cost retrieval on these documents (quotes from such pages can still contain
  misread characters: hence the warning below).
- **Low-confidence warning (I9): 0.955** for tiny. Pages with > 2% CER scored ≤ 0.939, good
  pages ≥ 0.970: 31/31 bad pages flagged, 0 false alarms. The scale is model-specific (small:
  bad ≤ 0.978, good ≥ 0.975, best cut 0.98 with 2 false alarms; Tesseract: anywhere 0.80–0.90).
  Measured on synthetic degradations: re-check on real scans.
- **DPI (I6): 200 kept.** 300 DPI and "full resolution" (no shrinking to 2000 px) gave no
  accuracy gain and cost time.
- **Paragraph recovery** (share of reference paragraphs rebuilt exactly, OCR + layout, tiny):
  clean **89%**, noisy **90%**, fax 12% (one misread character breaks an exact match). The first
  layout (gap rule + `split_paragraphs`) scored 87% / 75%; the remaining clean misses are mostly
  paragraphs whose last line reaches the right margin on uniformly spaced pages, so they merge
  with the next one. Text and retrieval are unaffected (chunks pack whole paragraphs anyway).
- **NFR-1** (50-page scan Ready ≤ 5 min): OCR ≈ 1.9–2.6 s/page with tiny → ≈ 2 min for 50
  pages, plus chunking and embedding (≈ 1 s per 10 chunks with bge-base). Not yet timed as one
  end-to-end 50-page upload in the app.
- **Contention caveat:** another job used the CPU during parts of the bake-off; speeds in the
  table come from runs on a quiet CPU, accuracy figures are unaffected by load.

## 7. Deviations from the plan

| Plan | Built | Why |
|---|---|---|
| I5 engine "picked by bake-off" | RapidOCR **tiny** (not the bundled small) | Small fails NFR-1 on this laptop; tiny beats Tesseract on bad scans and installs with pip (§6). Tiny's models download once (a few MB) into `<models_dir>/rapidocr`. |
| Angle classifier (RapidOCR default: on) | **Off** (`LL_AI_OCR_ANGLE_CLS=false`) | It rotated upright lines 180° and turned them into garbage (clean CER 0.03% → 1.3%). PDFium already applies page rotation. Upside-down scans become a known gap (§8). |
| I7 layout: gap > 0.55× row height, then `split_paragraphs` | **Geometry-based paragraphs** ([layout.py](src/legallens_ai/ingestion/layout.py)) | The bake-off showed two failures: full-width ALL-CAPS clause lines were split off as "headings", and pages of one-line paragraphs were merged. Now: a step break only when the page shows two spacings; a sentence-ending row that stops short of the margin ends a paragraph; a heading must be a short row at a paragraph start; steps are measured at each row's left end so a skewed scan doesn't fake paragraph gaps. Also restores "1.Term" → "1. Term". |
| I9 warning threshold 0.80 | **0.955** | 0.80 never fired: RapidOCR scores stay high on bad pages (§6). |
| `legallens-ai ingest` command | `legallens-ai index [--pages]` | One command for fixtures and real files; `--pages` prints each page's route, confidence and time. The old dev-only PDF/DOCX loader in `retrieval/loaders.py` is gone (JSON fixtures only). |
| Backend: only a thin adapter | + `Container.shutdown` calls the pipeline's optional `aclose()` | Embedded Qdrant must be closed to release its folder lock. |
| — | A damaged page that can't be rendered is reported blank (warning), not a failed document | One bad page shouldn't sink a 300-page upload. |
| — | `models_dir` → `<LL_DATA_DIR>/models` when `ai/` is installed as a package (Docker) | The default would point inside the virtualenv. From a source checkout models stay shared in `ai/data/models`. |
| — | Backend lock file now records `ai/`'s metadata | After any change to `ai/pyproject.toml`, run `uv lock` in `backend/` (CI's `--locked` catches it; the backend workflow now also runs on `ai/**`). Deploying with uv needs `backend/` and `ai/` side by side. |
| Docker: "context must include ai/" | Context = repo root, `backend/Dockerfile.dockerignore` **allow-list** replaces `backend/.dockerignore`, `LL_EXTRAS` build arg | Only source files can enter the image; the default image (no AI) is unchanged. |
| — | Dev group `bench` (pytesseract, rapidfuzz), dev dep `fpdf2`, pytest marker `ocr` | Bake-off and test tooling only; not installed in the app. |

## 8. Known gaps and next steps

- **Not checked in a browser.** The upload → OCR → Ready → delete flow is covered through the
  HTTP API (backend integration test), not clicked through in the UI.
- **Docker images not built locally** (no Docker here). The Dockerfile's install steps were
  dry-run on the same layout; CI builds both variants on the first push.
- **`ai/.venv` is not synced** with the new dependencies: a `legallens-ai classify` session from
  Oct 9 holds its executable. After closing it: `cd ai && uv sync --all-groups` (plain
  `uv sync` would remove the `qwen` group, i.e. torch).
- **Synthetic scans only.** Thresholds (text-layer 20 chars, confidence 0.955, paragraph steps)
  were tuned on rendered pages. Next: a handful of real scanned contracts, ideally with typed
  ground truth.
- Layout handles single-column pages; **two-column pages** are read across both columns.
  **Upside-down pages**, tables inside scans, handwriting and DOCX images are not handled.
  Scanner PDFs with a poor hidden text layer count as digital.
- No end-to-end 50-page timing in the app yet (NFR-1 estimate in §6 is from per-page timings).
- Under memory pressure (≈ 2 GB free) RapidOCR once raised `ResizeImgError` (OpenCV couldn't
  allocate). In the app that maps to `ocr_failed` (retryable), so the job runner retries it.
