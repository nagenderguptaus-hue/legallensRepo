# Legal Lens — Backend TODO (FastAPI, standalone)

> **Status:** approved and **implemented** 2026-10-05. 91 tests pass, coverage 93%, ruff and mypy strict clean. Open items: Docker build and CI run (§11). · **Scope:** backend only. No orchestration, no RAG, no models.
> **Added goal:** the backend must deploy and run in other environments (other machines, other OSes, containers), not just this laptop. See Phase 13.
> **Traces to:** [LegalLens_BRD.md](../LegalLens_BRD.md) v1.1 (FR/NFR ids) · [architecture/legal_lens_flow.excalidraw](../architecture/legal_lens_flow.excalidraw) (layer 2 + SQLite + file store) · the frontend contract in [frontend/src/api/types.ts](../frontend/src/api/types.ts)

---

## 1. Approach in one paragraph

We build the real FastAPI service: REST and SSE endpoints, validation, SQLite storage, the local file store, conversation history, the ingestion job runner, logging, tests and CI. Everything the AI layer will do later sits behind **two interfaces (ports)**: `ChatOrchestrator` and `IngestionPipeline`. For now the backend ships **stand-in adapters** for both. They are deterministic and use no models, so the backend can be run, demoed and tested end to end on its own (BRD Phase 2: "integration tests pass using a mock LLM"). In Phase 3 the AI layer provides real adapters, and switching to them is a config change (`LL_ORCHESTRATOR`, `LL_INGESTION`) with no changes to routes, services or the database. The **source of truth for the API contract is the frontend's `api/types.ts`**, which is a superset of the diagram (see §2.5). Integration later is then just: start the backend, set `VITE_USE_MOCKS=false`, add a Vite proxy.

---

## 2. API contract

### 2.1 Conventions
- Base path `/api`. JSON everywhere except the upload (multipart) and the chat stream (SSE).
- **Field casing follows the frontend types exactly:**
  - Resources use camelCase (`sizeBytes`, `uploadedAt`, `documentDeleted`, `totalPages`, …).
  - The chat request, SSE control payloads and the error envelope use snake_case (`conversation_id`, `document_ids`, `message_id`, `request_id`).
  - Pydantic aliases handle both. No casing is converted in the frontend.
- **IDs** are opaque prefixed strings: `doc_…`, `conv_…`, `msg_…`, `req_…`.
- **Timestamps** are ISO 8601 UTC, always with millisecond precision and a `Z` suffix (`2026-10-05T14:03:22.418Z`). Fixed width, so the frontend's string sorting stays correct.
- **Errors:** every non-2xx response has the body `{ "code", "message", "request_id" }`. Every response carries an `X-Request-ID` header.
- Deletes return `204` with no body.

### 2.2 System
| Method | Path | Response | Notes |
|---|---|---|---|
| GET | `/api/health` | `200 Health` `{ status: ok\|degraded, modelRuntime: ready\|loading\|unavailable, model }` | Checks SQLite, data dir writable, `orchestrator.health()`. Always 200, `degraded` when something is down. |

### 2.3 Documents (FR-1 – FR-5)
| Method | Path | Request | Success | Errors |
|---|---|---|---|---|
| GET | `/api/documents` | — | `200 LegalDocument[]`, newest first | — |
| POST | `/api/documents` | multipart field `file` | `201 LegalDocument` (`status: processing`, `stage: validating`) | 400 `missing_file` · 415 `unsupported_type` · 422 `empty_file` · 413 `file_too_large` · 422 `too_many_pages` · 422 `encrypted_file` · 422 `unreadable_file` · 409 `duplicate_document` · 409 `library_full` |
| GET | `/api/documents/{id}` | — | `200 LegalDocument` (polled by the UI during ingestion) | 404 `document_not_found` |
| POST | `/api/documents/{id}/retry` | — | `200 LegalDocument` (back to processing) | 404 `document_not_found` · 409 `document_not_failed` |
| GET | `/api/documents/{id}/pages/{n}` | — | `200 DocumentPage` `{ documentId, page, totalPages, paragraphs[], ocr, ocrConfidence }` | 404 `document_not_found` · 404 `page_not_found` · 409 `document_not_ready` |
| DELETE | `/api/documents/{id}` | — | `204` | 404 `document_not_found` |

**Delete** (FR-5, FR-21): cancels a running ingestion job, then removes the file, the page text, chunks, FTS rows and vectors (via `pipeline.purge`). Conversations that used the document stay and get `documentDeleted: true`. Their citations keep a snapshot of the document name.

### 2.4 Conversations (FR-19, FR-20)
| Method | Path | Request | Success | Errors |
|---|---|---|---|---|
| GET | `/api/conversations` | — | `200 Conversation[]`, most recently updated first | — |
| POST | `/api/conversations` | `{ title?, documentId? }` | `201 Conversation` (default title `New conversation`) | 404 `document_not_found` |
| GET | `/api/conversations/{id}` | — | `200 ConversationDetail` (messages oldest first, each with `citations`, `suggestions` and `error` if failed) | 404 `conversation_not_found` |
| PATCH | `/api/conversations/{id}` | `{ title?, documentId? }` | `200 Conversation` | 422 `invalid_title` · 404 `conversation_not_found` · 404 `document_not_found` |
| DELETE | `/api/conversations/{id}` | — | `204` (messages and citations go with it) | 404 `conversation_not_found` |

Titles are trimmed and capped at 120 characters. Setting `documentId` clears `documentDeleted`.

### 2.5 Chat stream (FR-6 – FR-18, FR-22)
`POST /api/chat/stream` · body `{ conversation_id, message, document_ids[] }` · response `text/event-stream`

**Rejected before the stream starts** (normal JSON error):
404 `conversation_not_found` · 422 `empty_message` · 422 `message_too_long` (> 8,000 chars) · 422 `too_many_documents` (v1 allows one, FR-6) · 404 `document_not_found` · 409 `document_not_ready` · 409 `conversation_busy` (a reply is already streaming) · 503 `model_unavailable`

**Event sequence:**
```
event: intent
data: {"intent":"ask","message_id":"msg_…","user_message_id":"msg_…"}

event: status
data: {"label":"Searching the document…"}

event: token
data: {"text":"The agreement lasts "}

event: citation
data: {"index":1,"documentId":"doc_…","documentName":"Mutual_NDA.docx","page":2,"section":"4. Term","quote":"…"}

event: done
data: {"message_id":"msg_…","user_message_id":"msg_…","outcome":"answered","suggestions":[],"title":"What is the term of the NDA"}
```
`outcome` is one of `answered | not_found | clarify | needs_document`. A failure mid-stream sends `event: error` with `{code, message, request_id}` and the stream ends. There is never a `done` after an `error`. A `: ping` comment is sent every 15 s to keep the connection open.

**Rules:**
- The user message and an empty assistant message (`status: streaming`) are saved **before** the first event. `intent` is always the first event.
- **Stop** (the client aborts): the assistant message is saved as `stopped` with the text generated so far.
- **Failure:** the message is saved as `error` with the error envelope, which `GET /api/conversations/{id}` returns.
- Ask or Summary with no document → `outcome: needs_document` and a friendly reply. This is not a 4xx (same as the frontend mock).
- The first message replaces the `New conversation` title with the message text (≤ 48 chars), returned in `done.title`.
- Sending with a document sets the conversation's `documentId` and clears `documentDeleted`.
- After a crash or restart, any message still `streaming` is marked `error` (`stream_interrupted`).

### 2.6 Diagram vs frontend contract: what I'm adopting
| Topic | Diagram | Frontend `types.ts` | Backend does |
|---|---|---|---|
| SSE extras | `intent`, `token`, `citation`, `done {message_id}`, `error` | adds the `status` event, message ids on `intent`, and `outcome`/`suggestions`/`title` on `done` | Frontend version |
| Citation payload | `{source, doc_id, page, section, quote}` | `{index, documentId, documentName, page, section, quote}` | Frontend version |
| Retry | — | `POST /api/documents/{id}/retry` | Implemented |
| Page preview | PNG files in `data/pages/` | text `paragraphs[]` per page | Text from a `document_pages` table. PNG rendering is left to Phase 3. |
| Mock controls | — | `/api/__mock/*` (only used when `VITE_USE_MOCKS` is on) | Not implemented. The same simulations come from env flags (§3). |

---

## 3. Interfaces to the AI layer (ports) and stand-ins

```python
class ChatOrchestrator(Protocol):
    def stream(self, ctx: ChatContext) -> AsyncIterator[OrchestratorEvent]: ...
    async def health(self) -> RuntimeHealth: ...


class IngestionPipeline(Protocol):
    async def run(self, item: IngestionInput, progress: ProgressReporter) -> IngestionResult: ...
    async def purge(self, document_id: str) -> None: ...  # drop the chunks/vectors it owns
```
- **`ChatContext`:** request id, conversation id, message, the selected document (id, name, type, pages) or `None`, the last N turns, and a read-only page-text reader.
- **`OrchestratorEvent`:** `Intent | Status | Token | Citation | Done(outcome, suggestions)`. The orchestrator never touches HTTP or writes to the DB. `ChatService` assigns ids, saves, and encodes the SSE.
- **`IngestionResult`:** pages (`page, paragraphs, section, ocr, ocr_confidence`), `is_scanned`, warnings. `ProgressReporter.update(stage, current, total)` writes the live progress the UI polls.
- **Errors:**
  - `ModelUnavailableError` → 503 or the SSE error `model_unavailable`
  - `ModelTimeoutError` → `model_timeout`
  - `IngestionFailed(user_message, retryable)` → document shows Failed with that message

**Stand-in adapters** (`adapters/standin/`, named so nobody mistakes them for AI):
- **`BasicIngestionPipeline`:** extracts text per page from PDFs (pypdf) and per section from DOCX (python-docx, using headings and page breaks).
  - Pages with no text layer get a warning.
  - A file with no text at all fails with *"This looks like a scanned document. OCR arrives with the AI layer."*
  - No chunking or embeddings.
- **`RuleBasedOrchestrator`:** a Python port of the frontend mock engine, but working on the **real extracted text**.
  - Intent comes from keyword rules.
  - **Ask:** finds the best passages by keyword overlap and quotes them as citations, or returns `not_found`.
  - **Summary:** the 6 fixed sections, each cited or marked "Not found in document".
  - **Draft:** a memo or case brief template with `[CITATION NEEDED]` and `[CONFIRM: …]` placeholders.
  - **Clarify:** returns quick-reply suggestions.
  - Streams tokens with a configurable delay. `/api/health` reports the model as `Stand-in (no AI)`.
- **Simulation flags** (for demos and tests): `LL_STANDIN_MODEL_OFFLINE`, `LL_STANDIN_TOKEN_DELAY_MS`, `LL_STANDIN_FAIL_MIDSTREAM`.

---

## 4. Data model — SQLite `data/legallens.db`

Tables from the diagram, with the columns the contract needs. **New** = not in the diagram.

| Table | Columns |
|---|---|
| `documents` | id · name · type · size_bytes · **sha256** (unique) · pages · is_scanned · status · stage · progress_current · progress_total · warnings (JSON) · error · uploaded_at · updated_at |
| `document_pages` **new** | document_id · page · section · paragraphs (JSON) · ocr · ocr_confidence — PK (document_id, page) |
| `ingestion_jobs` | id · document_id · state (queued/running/succeeded/failed/cancelled) · attempts · error · created_at · started_at · finished_at |
| `conversations` | id · title · document_id (plain id, no FK, so it survives deletion) · document_deleted · created_at · updated_at |
| `messages` | id · conversation_id (FK, cascade) · seq · role · content · status · intent · outcome · suggestions (JSON) · document_id · error_code · error_message · error_request_id · created_at |
| `citations` | id · message_id (FK, cascade) · idx · document_id · document_name (snapshot) · page · section · quote · chunk_id (nullable) |
| `chunks` + `chunks_fts` | Created now and left **empty**. Filled by Phase 3. Deleted with their document. |
| `transactions` | id · request_id · action · entity_id · status · error_code · latency_ms · ttft_ms · created_at |

Pragmas: `journal_mode=WAL`, `foreign_keys=ON`, `busy_timeout=5000`. Uploaded files go in `data/uploads/{doc_id}/original.{pdf|docx}`. The `data/` folder is git-ignored.

---

## 5. Tech stack (backend)

| Concern | Choice | Why |
|---|---|---|
| Runtime | **Python 3.12**, pinned by uv (your system 3.14 is left alone) | BRD baseline; best wheel coverage for the OCR/ML libraries Phase 3 will add |
| Packaging | **uv** + `uv.lock` | NFR-12 |
| Web | **FastAPI** + **Uvicorn** | Decided in the BRD |
| SSE | Starlette `StreamingResponse` + a ~20-line encoder | No extra dependency; we control pings and disconnect handling |
| Validation / config | **Pydantic v2** + **pydantic-settings** (`LL_` env prefix, `.env`) | Typed contracts, aliases for camel/snake case |
| Database | **SQLAlchemy 2.0 (async)** + **aiosqlite**, **Alembic** migrations | Typed models, real migrations for users who upgrade, FTS5 via raw SQL in a migration |
| File checks | **pypdf**, **python-docx**, stdlib `zipfile`/`hashlib` | Magic bytes, encryption, page count and dedupe with no native dependencies (no libmagic on Windows) |
| Uploads | python-multipart, streamed to disk in 1 MB chunks | 25 MB cap enforced while reading, not after |
| Logging | **structlog** (JSON) | NFR-10 |
| Tests | **pytest**, pytest-asyncio, httpx (ASGI transport), **fpdf2** (dev only, builds test PDFs) | No binary fixtures checked in |
| Quality | **ruff** (lint + format), **mypy --strict** | NFR-12 |
| CI | GitHub Actions | BRD §6 |

---

## 6. Folder skeleton (created after approval)

```
LegalLens/backend/
├── pyproject.toml · uv.lock · .python-version · .env.example · .gitignore · README.md · alembic.ini
├── src/legallens/
│   ├── main.py                 # create_app(), lifespan, `legallens-api` entry point
│   ├── config.py               # Settings: host, port, data dir, limits, adapters, flags
│   ├── logging.py              # structlog JSON setup, request-id contextvar, timed() helper
│   ├── api/
│   │   ├── middleware.py       # request id, access log + latency, CORS
│   │   ├── errors.py           # ApiError, error codes, exception handlers → envelope
│   │   ├── deps.py             # DI: session, services, settings
│   │   ├── sse.py              # SSE encoder + keep-alive
│   │   ├── schemas/            # common · documents · conversations · chat · health
│   │   └── routes/             # health · documents · conversations · chat
│   ├── services/               # document_service · conversation_service · chat_service · transaction_logger
│   ├── ingestion/              # validation (magic bytes, limits) · job_runner (queue, retries, recovery)
│   ├── storage/                # file_store (atomic writes, delete dir)
│   ├── db/                     # engine · models · repositories/ · migrations/ (Alembic)
│   ├── ports/                  # orchestrator.py · ingestion.py — the interfaces Phase 3 implements
│   └── adapters/standin/       # rule_based_orchestrator.py · basic_ingestion.py
├── tests/
│   ├── conftest.py · factories.py (builds PDFs/DOCX in code)
│   ├── unit/ · integration/ · contract/
└── scripts/                    # export_openapi.py · seed_demo.py
```
CI workflow: `LegalLens/.github/workflows/backend.yml` (the repo root). As built, `api/schemas/` became a single `api/schemas.py`, and `db/` has no `repositories/` (see Phase 3).

---

## 7. TODO — phased

### Phase 0 · Prerequisites
- [x] Install **uv** (`winget install astral-sh.uv`), then confirm: uv 0.12.23
- [x] `uv python install 3.12`, then confirm: CPython 3.12.15 (system Python 3.14.6 left as it is)
- [x] Install Git (`winget install Git.Git`), then confirm: git 2.55.0
- [x] `git init` at `LegalLens/` (branch `main`) with root `.gitignore` and `.gitattributes`. **No commit yet:** set your Git identity first (§11).
- [x] Get your approval of this TODO and answers to §9 (all recommendations accepted)

### Phase 1 · Scaffold
- [x] `uv init` the `legallens` package (src layout), add runtime and dev dependencies (§5), commit `uv.lock`
- [x] ruff and mypy-strict config in `pyproject.toml`. `.gitignore` covers `.venv/`, `data/` and `.env`.
- [x] `config.py`: host `127.0.0.1`, port `8000`, data dir, limits (25 MB · 300 pages · 100 docs · 8,000 chars · history N=10), adapter selection, stand-in flags, CORS origins. Plus `.env.example`.
- [x] `create_app()` + lifespan: run migrations, start the job runner, recover interrupted work, stop cleanly on shutdown
- [x] Refuse to start on a non-loopback host unless `LL_ALLOW_REMOTE=true` (NFR-5)

### Phase 2 · Cross-cutting (NFR-5, NFR-10, BRD §6)
- [x] Request-ID middleware: reuse a valid incoming `X-Request-ID`, otherwise generate `req_…`. Stored in a contextvar and echoed in the response header.
- [x] Error envelope + handlers:
  - `ApiError` → its own status and code
  - validation error → 422 `validation_error` with a human-readable message
  - unknown route → 404 `not_found`; wrong method → 405 `method_not_allowed`
  - unhandled exception → 500 `internal_error` (stack logged, never returned)
- [x] structlog JSON access log: request_id, method, route, status, latency_ms. **Never** request bodies, document text, prompts or file names (document ids only).
- [x] `timed("step")` helper for per-step timings in services
- [x] CORS limited to `http://localhost:5173` and `http://127.0.0.1:5173` (configurable)
- [x] `TransactionLogger`: one row per user action (`document.upload/retry/delete`, `conversation.create/rename/delete`, `chat.message`) with status, latency and, for chat, ttft and outcome

### Phase 3 · Database
- [x] Async engine + session factory with the pragmas in §4
- [x] ORM models for every table in §4
- [x] Alembic setup + initial migration (FTS5 virtual table via raw SQL). Migrations run automatically on startup.
- [x] ~~Repositories per aggregate~~ **Changed:** services query through SQLAlchemy directly, each in a short-lived session. A repository layer would only have wrapped one-line queries.
- [x] ID and UTC timestamp helpers (§2.1 format)

### Phase 4 · File store & upload validation (FR-1, FR-2, NFR-3, NFR-5)
- [x] `FileStore`: `data/uploads/{doc_id}/original.{ext}`, atomic write (temp file + rename), delete folder
- [x] Stream the upload to a temp file and stop at > 25 MB → 413. The `Content-Length` header is not trusted.
- [x] Detect type by **content**:
  - PDF: starts with `%PDF-`
  - DOCX: a ZIP containing `[Content_Types].xml` and `word/document.xml`
  - anything else → 415, including `.doc` and renamed files
- [x] Reject bad files:
  - encrypted PDF → `encrypted_file`
  - corrupt file → `unreadable_file`
  - more than 300 pages → `too_many_pages`. PDF pages come from pypdf; DOCX pages from `docProps/app.xml`, otherwise estimated.
- [x] SHA-256 dedupe → `duplicate_document`. Library cap of 100 → `library_full`.
- [x] Clean the display name (strip paths and control characters, ≤ 255 chars). The name is **never** used in file paths.

### Phase 5 · Ingestion job runner (FR-3, NFR-8)
- [x] asyncio queue with **one worker**, started in lifespan. Upload and retry add a job and an `ingestion_jobs` row.
- [x] `ProgressReporter` writes stage, current page and total pages to the `documents` row, at most 2 writes per second
- [x] Error handling:
  - transient errors → up to 2 retries with backoff
  - `IngestionFailed` → document marked Failed with its message
  - per-job timeout, 10 min by default
- [x] CPU-bound work runs in `asyncio.to_thread` so the API stays responsive
- [x] On success: save pages, warnings, page count and `is_scanned`, then mark the document Ready
- [x] On startup: re-queue documents stuck in Processing. Delete cancels an active job.

### Phase 6 · Documents API + `DocumentService`
- [x] All endpoints in §2.3, with every listed error code
- [x] Delete cascade (§2.3) including `pipeline.purge()` and `documentDeleted` on conversations
- [x] Page endpoint reads from `document_pages`

### Phase 7 · Conversations API + `ConversationService`
- [x] All endpoints in §2.4. The detail view includes messages with citations, suggestions and the error envelope.
- [x] Title rules, `documentId` validation, and cascade delete of messages and citations

### Phase 8 · Chat API + `ChatService` (SSE)
- [x] Pre-stream checks in the order listed in §2.5. One active stream per conversation (in-memory lock).
- [x] Build `ChatContext` (last N turns, document metadata, page reader) and save the user and assistant rows before the first event
- [x] Relay orchestrator events as SSE. Save partial content about once a second so a crash keeps the text.
- [x] **Citation guard:**
  - indexes are unique
  - `documentId` is the selected document
  - the page is in range
  - invalid citations are dropped and logged. The full verifier is Phase 3.
- [x] Handle `done`, `error`, client disconnect (→ `stopped`), `: ping` every 15 s, and the headers `Cache-Control: no-cache` and `X-Accel-Buffering: no`
- [x] Timeouts: first event ≤ 30 s, whole reply ≤ 5 min (configurable) → `model_timeout`
- [x] Auto-title. Write a transaction row with ttft, total latency and outcome.

### Phase 9 · Stand-in adapters
- [x] `BasicIngestionPipeline` (§3)
- [x] `RuleBasedOrchestrator` (§3), including the `status` labels and all four outcomes
- [x] Adapters chosen by config. Health reports `Stand-in (no AI)`.

### Phase 10 · Health
- [x] `GET /api/health`: SQLite `SELECT 1`, data dir writable, `orchestrator.health()` → `ok` or `degraded` + `modelRuntime`

### Phase 11 · Tests (BRD §6)
- [x] **Unit:** magic-byte detection, page counting, limits, name cleaning, SSE encoder, title rule, ID/timestamp format, error-envelope mapping, stand-in intent rules
- [x] **Integration** (httpx ASGI client, temporary data dir, stand-ins):
  - upload → Processing → Ready (polling) → page preview
  - corrupt or scanned file → Failed → retry
  - duplicate, too large and wrong type
  - delete cascade → `documentDeleted`
  - conversation CRUD
  - chat: ask with citations · not found · summary · draft placeholders · clarify · needs document
  - stop → `stopped`; mid-stream failure → `error` saved; model offline → 503; busy → 409
  - restart recovery (stuck jobs, stuck streams)
- [x] **Contract:** response key sets checked against the frontend types, plus a committed `openapi.json` snapshot test
- [x] **Demo path:** the BRD §7 flow as one test (upload → ask → unanswerable → summary → draft → "restart" → reopen → delete)
- [x] Test files generated in code: a text PDF, a PDF with no text layer, an encrypted PDF and a DOCX
- [x] Coverage ≥ 85% on `api/` and `services/`

### Phase 12 · CI, docs & developer experience
- [x] GitHub Actions: `uv sync --locked` → `ruff check` → `ruff format --check` → `mypy` → `pytest` (`.github/workflows/backend.yml`; all steps pass locally)
- [x] README:
  - setup and run (`uv run legallens-api`)
  - configuration table
  - a curl example for every endpoint
  - how Phase 3 plugs in its adapters
  - how to connect the frontend (Vite proxy snippet + `VITE_USE_MOCKS=false`)
- [x] `scripts/export_openapi.py`. Swagger UI at `/api/docs` (local only).
- [x] `scripts/seed_demo.py`: loads a **synthetic** NDA (PDF) and lease (DOCX), generated in code, plus one answered conversation. Swap in public-domain documents for the class demo.
- [x] `ruff`, `mypy` and `pytest` all green with zero warnings

### Phase 13 · Portability & deployment (your added goal)
- [x] **Config only through env vars / `.env`** (12-factor). Nothing machine-specific in code. Every setting is in `.env.example` and the README.
- [x] **Data dir** set by `LL_DATA_DIR` (default `./data` next to the backend), created on startup. All paths use `pathlib`. File names are never built from user input.
- [x] **No native build steps** (no libmagic, no compilers): every dependency ships pre-built wheels for Windows, macOS and Linux, so `uv sync --locked` gives the same environment everywhere.
- [x] `.gitattributes` with LF line endings, so scripts and the Dockerfile work when checked out on Linux
- [ ] **Dockerfile** (written, **not built yet**: Docker isn't installed on this machine; CI's `docker` job builds and smoke-tests it):
  - multi-stage build with uv and `python:3.12-slim`
  - non-root user and a `/data` volume
  - `HEALTHCHECK` on `/api/health`
  - inside the container the app binds `0.0.0.0` with `LL_ALLOW_REMOTE=true`
- [ ] **`compose.yaml`** (written, not run yet, same reason) (backend service) publishes on `127.0.0.1:8000` only, so the host stays loopback-only (NFR-5). The frontend service is added at integration.
- [ ] **CI matrix** on `ubuntu-latest`, `windows-latest` and `macos-latest`, plus a job that builds the Docker image and smoke-tests `/api/health` (workflow written; runs once the repo is pushed to GitHub)
- [x] `uv run legallens-api` entry point and `python -m legallens` both work. On shutdown the worker stops; an interrupted job stays Processing and is re-queued on the next start (tested).
- [x] README "Deploy elsewhere" section: bare metal with uv, and Docker/Compose

---

## 8. Out of scope (this phase)
- LangChain, the LLM intent router, the query editor and RAG
- Chunking, embeddings, the vector store, re-ranking, OCR and layout models
- Managing the model runtime
- Docker Compose for the whole stack (integration step)
- Frontend changes (the Vite proxy is a ~5-line change at integration)
- Auth and multi-document Q&A

---

## 9. Questions for your review (my recommendation first)

> **Resolved 2026-10-05:** every recommendation below was accepted: stand-ins at runtime · job runner in the backend · synchronous upload checks · Git installed + repo · Python 3.12 · SQLAlchemy async + Alembic.

1. **Stand-ins at runtime.** Should the backend *run* (not just test) with the stand-in adapters, producing real-looking answers from the real extracted text? **Recommended: yes.** You can demo the backend alone and integrate the frontend before Phase 3. The alternative is stand-ins in tests only, which means the backend can't answer chats until Phase 3.
2. **Where the ingestion job runner lives.** The diagram draws it in the orchestration row. **Recommended: backend.** It is queue, retry and status plumbing with no AI in it, and the frontend's polling depends on it. Phase 3 only provides the `IngestionPipeline` it calls.
3. **Upload validation timing.** Cheap checks (type, size, pages, encryption, duplicates) run **inside the upload request**, so the user gets an immediate 4xx, the same as the frontend mock. The diagram shows validation as the first ingestion stage. **Recommended: synchronous**, with the status still starting at `validating` for the UI.
4. **Git and CI.** Git isn't installed and `LegalLens/` isn't a repository, so the CI workflow can be written but won't run. **Recommended:** install Git and `git init` at `LegalLens/` before Phase 1. Or I write the workflow now and you set up the repo later.
5. **Python version.** Pin **3.12** (BRD baseline, safest for Phase 3's ML/OCR wheels), or use your installed 3.14?
6. **Database layer.** SQLAlchemy 2.0 async + Alembic (**recommended**: typed, safe schema upgrades) or plain `sqlite3` with hand-written SQL (fewer concepts for students, no migrations)?

---

## 10. Definition of done
- `uv run legallens-api` starts on `127.0.0.1:8000` and needs no network access.
- Every endpoint in §2 matches the contract, including every error code.
- The whole BRD §7 demo path works through Swagger or curl with the stand-ins.
- The frontend works against it with only `VITE_USE_MOCKS=false` and a Vite proxy, with no UI code changes.
- `ruff`, `mypy --strict` and `pytest` are green, with coverage ≥ 85% on `api/` and `services/`.
- Replacing the stand-ins with Phase 3 adapters is a config change only.

---

## 11. Open items after implementation
1. **Docker:** not installed here, so the image and `compose.yaml` are unbuilt. Either install Docker Desktop (`winget install Docker.DockerDesktop`; needs WSL2 and a reboot) and run `docker compose up --build` in `backend/`, or let the CI `docker` job verify it after the first push.
2. **First commit:** set your identity (`git config --global user.name "…"` and `user.email "…"`), then commit from `LegalLens/`.
3. **CI:** runs once `LegalLens/` is pushed to GitHub.
4. ~~**Integration (next step)**~~ **Done**: see [../integration.todo.md](../integration.todo.md). The full-stack Compose file and its CI smoke test live at the project root.
