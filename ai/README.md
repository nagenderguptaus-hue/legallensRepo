# Legal Lens — AI layer

The orchestrator's **intent router** (Phase 3a) and the **Ask, Summary and Draft workflows**
behind it (Phase 3b). Given the lawyer's latest chat message (and the last few turns), the router
decides which workflow should handle it:

| Intent | Workflow | Needs a selected document |
|---|---|---|
| `ask` | Answer a specific question from the document, with citations | yes |
| `summary` | Six-section summary of the whole document | yes |
| `draft` | Memo, case brief or free-form legal writing | no |
| `clarify` | Ask the lawyer a follow-up question | no |

It also holds **document ingestion** (Phase 3c): every uploaded page is read by a loader or, if
it is a scan, by OCR, then chunked, embedded and stored for search. Ingestion is wired into the
backend through an optional adapter (see "Ingestion" below). Since Phase 3d the backend's chat
runs through the router and the workflows too (see "In the app: chat" below). Plans and design
decisions: [TODO.md](TODO.md) (router), [workflows.todo.md](workflows.todo.md) (workflows),
[ingestion.todo.md](ingestion.todo.md) (ingestion), [orchestration.todo.md](orchestration.todo.md)
(backend chat wiring).

## The intent router

```
OrchestratorRequest(message, history, document)
        │
        ▼
IntentClassifier  ── LCEL: ChatPromptTemplate | ChatAnthropic(claude-haiku-4-5)
        │                    .with_structured_output(IntentClassification, method="json_schema")
        │          system prompt = prompts/intent_classifier.prompt.md (verbatim)
        ▼
{rationale, intent}   ← schema-constrained by the API: always one of the four intents
        │
        ▼
Orchestrator rule: ask/summary with no document → needs_document = true
        │
        ▼
RoutingDecision(intent, needs_document, rationale, model, latency_ms, usage)
```

| File | What it is |
|---|---|
| [src/legallens_ai/prompts/intent_classifier.prompt.md](src/legallens_ai/prompts/intent_classifier.prompt.md) | The domain knowledge: how a legal subject-matter expert tells ask, summary, draft and clarify apart. **The whole file is sent to the model as the system prompt.** Edit it, then rerun the eval. |
| [src/legallens_ai/intent_classifier.py](src/legallens_ai/intent_classifier.py) | The LangChain chain, how history is framed, error mapping |
| [src/legallens_ai/orchestrator.py](src/legallens_ai/orchestrator.py) | `Orchestrator.route()`: classify, then apply the document rule |
| [src/legallens_ai/schemas.py](src/legallens_ai/schemas.py) | Request / result types (mirror the backend's `ports/orchestrator.py`) |
| [evals/intent_cases.jsonl](evals/intent_cases.jsonl) | 43 labelled messages, including follow-ups and prompt-injection cases |

> **Privacy note.** The BRD (G5, NFR-4) calls for local models only. This layer uses Claude, so
> text goes to Anthropic's API: the router and the query rewriter send the message and up to 6
> earlier turns; **Ask sends the 8 retrieved passages; Summary and Draft send the whole selected
> document.** Embeddings, keyword search and reranking run locally. Use synthetic or public
> documents for demos.

## The workflows

Every workflow takes an `OrchestratorRequest` and yields the backend's stream events:
`status`, `token`, `citation` (each `[n]` in the text) and a final `done` with the outcome.

### Ask: hybrid RAG with citations

```
question + history
  │ pre-retrieval   no history → searched as is, no model call
  │                 else Haiku 4.5: "standalone" → original kept verbatim (code-enforced)
  │                                 "follow_up"  → rewritten into a self-contained question
  ▼
  ├─ vector search: bge-large-en-v1.5 embeddings in Qdrant, top 25 ┐
  └─ BM25 keyword search: SQLite FTS5, top 25 ──────────────────────┴→ union (no duplicates)
  ▼
  cross-encoder reranker (bge-reranker-v2-m3; Qwen3-Reranker on a GPU) → top 8
  ▼
  best score < the reranker's calibrated gate (-7.0) ? → "I couldn't find this in the document." (no Sonnet call)
  ▼
  Sonnet 5.5: 8 passages as Claude `search_result` blocks + the question, streamed
  ▼
  native citations → [n] markers + citation events (page, section, exact quote)
```

Claude's citations are copied by the API from the passages we send, so a quote can't be
invented. Each paragraph is its own citable block, so a citation points at whole paragraphs.

### Summary

All chunks of the document, in order, as cited `search_result` blocks (prompt-cached) →
the six FR-12 sections. **Sonnet 5.5** writes it for documents up to ~60k tokens, **Opus 5.5**
above that. One pass, no map-reduce: anything within the BRD's 300-page limit fits the 1M-token
context. Afterwards, code checks that all six headings are present and each section is cited.

### Draft

**Opus 5.5** (effort `high`) infers memo / case brief / free-form from the instructions. With a
reference document, the whole document goes in as cited passages. Revisions ("make it shorter")
get the previous draft in full. Unknown facts must be `[CONFIRM: …]` and every legal authority
`[CITATION NEEDED: …]`; afterwards, code flags any case, reporter or statute citation that
appears in neither the instructions, the conversation nor the document.

### Files

| File | What it is |
|---|---|
| [prompts/query_rewriter.prompt.md](src/legallens_ai/prompts/query_rewriter.prompt.md) | The rewriter's rules: when not to rewrite, how to resolve references without adding facts |
| [prompts/ask.prompt.md](src/legallens_ai/prompts/ask.prompt.md), [summary.prompt.md](src/legallens_ai/prompts/summary.prompt.md), [draft.prompt.md](src/legallens_ai/prompts/draft.prompt.md) | Domain rules for each workflow |
| [query_rewriter.py](src/legallens_ai/query_rewriter.py) | Pre-retrieval, with the two guardrails in code |
| [retrieval/](src/legallens_ai/retrieval/) | Chunker, SQLite/FTS5 chunk store, Qdrant vector store, local models, indexer, hybrid retriever |
| [workflows/](src/legallens_ai/workflows/) | `ask.py`, `summary.py`, `draft.py`; `generation.py` (streaming + citations); `checks.py` (output checks) |
| [evals/](evals/) | Labelled cases for the router, the rewriter and Ask; synthetic documents in `evals/documents/` |

### Eval results

| Eval | Result |
|---|---|
| Intent router, 43 cases, real Haiku 4.5 (2026-10-14) | 43/43, p50 1.7 s, ~$0.11 (`evals/results/intent_run1.json`) |
| Query rewriter, 27 cases (2026-10-14) | 27/27 after a prompt pass for "source" questions ("where does it say that?") and "And what about X?" (24/27 before, on the same cases). Both guardrails held in every case. |
| Ask, 32 cases, first stack (bge-base + MiniLM, 2026-10-13) | Full run: 30/32. Both misses were wrong expected pages in the eval itself (the model cited the right page); after correcting them, those two cases passed on re-run. Correctness 25/25 (target ≥ 80%), correct citation 25/25 (≥ 90%), "not found" 7/7 (≥ 90%), retrieval recall 25/25, 0 uncited answers, both injection cases resisted. |
| Ask, 32 cases, current stack (bge-large + bge-reranker-v2-m3, 2026-10-14) | 31/32 as run. The miss was an eval rule penalising the model for neutrally quoting the planted injection (which the prompt asks for); with the rule corrected, the saved answer passes. Citation 25/25, "not found" 7/7, retrieval 25/25, 0 uncited, gate stopped 1 (off-topic). This small set can't tell the stacks apart; the LegalBench bake-off below can. |
| Ask latency | Generation: first text p50 1.0 s, full answer p50 2.5 s. Plus ~1.8 s rewrite on follow-ups. Retrieval: ~1 s with MiniLM; with bge-reranker-v2-m3 on a laptop CPU, up to ~50 s on long documents (seconds on a GPU) |

### Choosing the retrieval models (2026-10-14)

Open-source models only, compared on **LegalBench-RAG** (MIT; contract questions from CUAD,
MAUD and ContractNLI, plus PrivacyQA), with the gold passage marked for every question.
The sample was 104 questions over 21 documents, including 98k-word merger agreements, using
our real chunker and BM25. As in the app, each search stays inside one document.

| Embedding model | Candidates contain the answer | Long merger agreements |
|---|---|---|
| bge-base-en-v1.5 (old default) | 0.886 | 0.569 |
| snowflake-arctic-embed-m-long | 0.912 | 0.723 |
| **bge-large-en-v1.5 (default)** | **0.933** | **0.842** |
| Qwen3-Embedding-0.6B | 0.933 | 0.810 |

| Reranker (on bge-large's candidates) | Answer in the 8 sent to Sonnet | MRR | Time per question, laptop CPU |
|---|---|---|---|
| ms-marco-MiniLM-L-6 (old default) | 0.649 (worse than no reranker: 0.723) | 0.452 | ~2 s |
| **bge-reranker-v2-m3 (default)** | 0.810 | 0.615 | ~50 s |
| Qwen3-Reranker-0.6B (best; for GPU hosts) | **0.832** | **0.656** | ~3 min |

Rerun it with `uv run legallens-ai bench-retrieval --embedders … --rerankers … --rerank-on best`
after downloading the data (see [retrieval_bench.py](src/legallens_ai/retrieval_bench.py)).
Details and the "not found" gate calibration: [workflows.todo.md](workflows.todo.md),
Phase 3b.1.

## Ingestion: loader or OCR, then chunk → embed → store

```
PDF page ── text layer with ≥ 20 letters/digits? ──yes──→ loader (pypdf): text → paragraphs
                                                 └─no───→ render (PDFium, 200 DPI, grayscale)
                                                          → OCR (RapidOCR, ONNX, local)
                                                          → layout: lines → rows → paragraphs
DOCX ─────────────────────────────────────────────────→ loader (python-docx): paragraphs,
                                                          tables, Word page breaks
        ▼
quality check: OCR confidence per page → warnings; no text at all → the document fails
        ▼
DocumentIndexer (unchanged): ~300-word paragraph chunks, never across pages
        → bge-large embeddings → Qdrant (vectors) + SQLite FTS5 (keywords)
```

- **Routing is per page**, so a digital contract with a scanned signature page or exhibit works:
  only the scanned pages are OCR'd. A stamped page number alone ("Page 3") doesn't count as a
  text layer.
- **Everything runs locally**: no document text or image leaves the machine during ingestion.
  OCR uses RapidOCR's "tiny" models (chosen by a bake-off against Tesseract: see
  [ingestion.todo.md §6](ingestion.todo.md)); they download once (a few MB) into
  `data/models/rapidocr`, then everything works offline.
- Each OCR'd page records `ocr=True` and its **confidence** (character-weighted mean of the
  engine's line scores). The backend shows both, plus warnings such as "Low OCR confidence on
  page 3".
- Re-ingesting a document replaces its chunks and vectors; `purge` deletes them (FR-5).
- Not handled yet: two-column pages (read across both columns), upside-down scans, images
  inside Word files, and scanner-made PDFs whose hidden text layer is poor (treated as digital).

| File | What it is |
|---|---|
| [ingestion/pipeline.py](src/legallens_ai/ingestion/pipeline.py) | `DocumentIngestor`: per-page routing, quality check, indexing, errors |
| [ingestion/digital.py](src/legallens_ai/ingestion/digital.py) | The loader (ported from the backend stand-in, with its behaviour) |
| [ingestion/render.py](src/legallens_ai/ingestion/render.py) · [ocr.py](src/legallens_ai/ingestion/ocr.py) · [layout.py](src/legallens_ai/ingestion/layout.py) | Page rendering, the OCR engine interface, paragraph rebuilding |
| [runtime.py](src/legallens_ai/runtime.py) | `AIRuntime`: one shared retrieval stack per process (embedded Qdrant locks its folder) |
| [ocr_bench.py](src/legallens_ai/ocr_bench.py) | The OCR bake-off: synthetic scans at three qualities, error rates, speed |

**In the app:** from `backend/`, run `uv sync --extra ai` and set
`LL_INGESTION=legallens.adapters.ai:create_ingestion` (or the older
`legallens.adapters.ai_ingestion:create`, same pipeline). The index then lives in
`<LL_DATA_DIR>/ai/`. The backend's own README has the details.

## In the app: chat

One chat turn, as the backend runs it (`Orchestrator.stream()`):

```
message + history + selected document
  → router (Haiku 4.5)                       → IntentEvent (the UI's intent badge)
  → needs a document but none selected?      → fixed "select a document" reply
  → clarify                                  → template reply + 3 suggestion chips, no model call
  → ask / summary / draft                    → that workflow, streamed (status · token · citation · done)
```

| File | What it is |
|---|---|
| [orchestrator.py](src/legallens_ai/orchestrator.py) | `Orchestrator.route()` / `.stream()`, `TurnTrace` (per-turn metadata: models, tokens, timings, never text) |
| [engine.py](src/legallens_ai/engine.py) | `ChatEngine` on the shared `AIRuntime`: model warm-up, health status, backfill of documents not yet indexed, `stream()` |
| [workflows/clarify.py](src/legallens_ai/workflows/clarify.py) | The Clarify reply |
| [streams.py](src/legallens_ai/streams.py) | Closes each layer's stream down to the model's, so Stop really stops generation |

Turn it on in the backend with `LL_ORCHESTRATOR=legallens.adapters.ai:create_orchestrator`
(needs the AI ingestion above). ⚠️ Then messages, recent history and document passages (the whole
document for Summary and Draft) go to Anthropic's API; see the backend README.
Try the same turns from the terminal: `uv run legallens-ai chat --doc <id>`.

## Setup

Prerequisite: [uv](https://docs.astral.sh/uv/).

```bash
cd ai
cp .env.example .env          # then put your key in ANTHROPIC_API_KEY
uv sync
```

On OneDrive folders, uv can't hardlink; set `UV_LINK_MODE=copy` first (PowerShell:
`$env:UV_LINK_MODE="copy"`).

The first search or index downloads the embedding and reranker models (~3.6 GB) into
`data/models/`. Indexes live in `data/` (`chunks.db` + `qdrant/`), which git ignores.

## Testing it

| Command | What it does | Cost |
|---|---|---|
| `uv run pytest` | Unit tests with a fake model, plus one real OCR test (`-m "not ocr"` skips it) | free, offline |
| `uv run legallens-ai classify "Summarize this lease"` | Route one message | ~$0.003 |
| `uv run legallens-ai classify --no-document "When is rent due?"` | …as if no document were selected (`needs_document: True`) | ~$0.003 |
| `uv run legallens-ai classify --show-prompt "…"` | Also print the exact user turn sent to the model | ~$0.003 |
| `uv run legallens-ai classify` | Interactive: one message per line, empty line to quit | per message |
| `uv run legallens-ai eval` | Run all 43 labelled cases: accuracy, confusion matrix, misses with rationale, latency, tokens | ~$0.15 |
| `uv run legallens-ai eval --only fol inj` | Only the follow-up and injection cases | less |
| `uv run legallens-ai eval --out evals/results/run1.json` | Also save per-case results to compare prompt versions | — |
| `uv run pytest -m live` | 4 BRD demo messages against real Haiku, plus one Ask answer and one "not found" | ~$0.03 |
| `uv run legallens-ai index evals/documents/msa.json` | Index a page-fixture `.json` | free, local |
| `uv run legallens-ai index --pages contract.pdf` | Ingest a `.pdf` / `.docx` like the app does (OCR for scanned pages); `--pages` prints each page's route, confidence and time | free, local |
| `uv run legallens-ai docs` / `forget <id>` | List indexed documents / delete one's chunks and vectors | free |
| `uv run legallens-ai search --doc doc_msa "late fees"` | Retrieval only: vector rank, BM25 rank and rerank score per chunk | free, local |
| `uv run legallens-ai ask --doc doc_msa "Who are the parties?"` | One Ask answer, with citations, the rewrite and latency | ~$0.01 |
| `uv run legallens-ai ask --doc doc_msa` | Chat that keeps history, so follow-ups go through the rewriter (`--show-chunks` for the retrieval table) | per message |
| `uv run legallens-ai summarize --doc doc_msa` | Six-section summary, with the section check | ~$0.05 (Sonnet) |
| `uv run legallens-ai draft --doc doc_msa "Draft a memo on …"` | A draft; omit the text to chat and revise it | ~$0.15 (Opus) |
| `uv run legallens-ai chat --doc doc_msa` | Full chat turns as the backend runs them (router → workflow), with each turn's trace; omit `--doc` for none | per message |
| `uv run legallens-ai eval-rewrite` | 27 labelled rewrite cases | ~$0.07 |
| `uv run legallens-ai eval-ask --out evals/results/ask.json` | 32 Ask cases, scored against the BRD §6 targets | ~$0.45 |
| `uv sync --all-groups` then `uv run legallens-ai bench-ocr --configs rapid-small tesseract-300dpi` | OCR bake-off on synthetic scans (`--retrieval` adds the retrieval check). Tesseract configs need the Tesseract program. | free, local |

To add a case, append a line to `evals/intent_cases.jsonl`:

```json
{"id": "ask-14", "message": "...", "expected": "ask", "history": [{"role": "user", "content": "..."}, {"role": "assistant", "intent": "draft", "content": "..."}], "note": "why"}
```

Keep eval messages different from the examples in the prompt file (a unit test checks this),
so the score measures how well the rules generalise rather than memorisation.

## Configuration

Every setting is listed with its default in [.env.example](.env.example). The router's are:

Environment variables (or `.env`), all optional except the key:

| Variable | Default | |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | required |
| `LL_AI_INTENT_MODEL` | `claude-haiku-4-5` | |
| `LL_AI_INTENT_TEMPERATURE` | `0` | repeatable labels |
| `LL_AI_INTENT_MAX_TOKENS` | `512` | output is ~40 tokens |
| `LL_AI_INTENT_TIMEOUT_S` | `15` | per attempt |
| `LL_AI_INTENT_MAX_RETRIES` | `2` | SDK retries 429 / 5xx / network errors |
| `LL_AI_INTENT_HISTORY_TURNS` | `6` | earlier turns sent with the message |
| `LL_AI_INTENT_TURN_CHARS` | `600` | each earlier turn is cut to this length |

## Errors

Every failure raises an `OrchestratorError` with a stable `code`, matching the backend's error shape:

| Code | When | Backend should map to |
|---|---|---|
| `model_unavailable` | network error, timeout, 429, 5xx / overloaded (after retries) | 503 |
| `model_auth_missing` / `model_auth_failed` | no key / key rejected | 503 |
| `model_request_failed` | other 4xx, e.g. an unknown model id | 502 |
| `intent_unparseable` | the model refused or its output didn't fit the schema | 502 |
| `rewrite_unparseable` | the query rewriter's output didn't fit its schema | 502 |
| `model_refused` | a workflow model declined (`stop_reason: refusal`), even after the server-side fallback | 502 |
| `retrieval_unavailable` | the vector store, keyword index, embedding model or reranker failed | 503 |
| `document_not_indexed` | Ask / Summary / Draft on a document with no chunks yet | 409 |
| `document_too_large` | Summary / Draft on a document above `LL_AI_MAX_DOCUMENT_TOKENS` | 422 |

Workflows never fall back silently: a failed rewrite or rerank raises instead of answering from
worse evidence. Logs contain metadata only (intent, ranks, scores, latency, tokens, model),
never message or document text (NFR-5).
