# Legal Lens — Backend

FastAPI service for Legal Lens. It handles document upload and ingestion, conversation history, and the streamed chat API (Server-Sent Events). It runs entirely on `127.0.0.1` and stores everything in a local folder: the SQLite database and the uploaded files.

The AI layer (Phase 3) plugs in behind two interfaces. By default the backend runs end to end with built-in **stand-ins**:
- **Ingestion stand-in:** extracts real text from PDF and DOCX files. There is no OCR, so scanned files fail with a clear message. The **AI ingestion** (OCR for scanned pages, chunking, embeddings, vector index) replaces it with one setting: see "Plugging in the AI layer".
- **Chat stand-in:** answers with quoted passages and citations, using keyword rules. There is no AI model, and every reply says so.

> Requirements: [../LegalLens_BRD.md](../LegalLens_BRD.md) · Plan and status: [TODO.md](TODO.md) · API contract: [openapi.json](openapi.json)

---

## Quick start

Prerequisite: [uv](https://docs.astral.sh/uv/). uv installs the right Python (3.12) by itself.

```bash
cd backend
uv sync                      # create .venv from the lock file
uv run legallens-api         # http://127.0.0.1:8000  ·  API docs at /api/docs
```

In a second terminal, load the demo data: a synthetic lease (PDF) and NDA (DOCX), a scan that fails (blank pages, so even the AI ingestion's OCR finds no text), and five conversations covering ask, not found, summary, draft, clarify and a deleted source. Everything goes in through the API, so this works against any running instance.

```bash
uv run python scripts/seed_demo.py                 # add the demo data (safe to re-run)
uv run python scripts/seed_demo.py --fresh         # reset: delete everything, then seed (loopback only)
uv run python scripts/seed_demo.py --url http://127.0.0.1:8080   # e.g. the Docker stack
```

`python -m legallens` works too.

## Configuration

All settings are environment variables with the prefix `LL_`, or entries in a `.env` file in the working directory. To change a default, copy [.env.example](.env.example) to `.env`. The most important ones:

| Variable | Default | Purpose |
|---|---|---|
| `LL_DATA_DIR` | `data` | Folder for the SQLite DB (`legallens.db`) and uploads |
| `LL_HOST` / `LL_PORT` | `127.0.0.1` / `8000` | Bind address. Non-loopback hosts are refused unless `LL_ALLOW_REMOTE=true` (containers only). |
| `LL_CORS_ORIGINS` | `["http://localhost:5173","http://127.0.0.1:5173"]` | Frontend origins allowed to call the API |
| `LL_MAX_UPLOAD_MB` · `LL_MAX_PAGES` · `LL_MAX_DOCUMENTS` | `25` · `300` · `100` | Upload limits (NFR-3) |
| `LL_ORCHESTRATOR` · `LL_INGESTION` | `standin` | Which AI adapters to load (see below) |
| `LL_STREAM_FIRST_EVENT_TIMEOUT_S` · `LL_STREAM_TOTAL_TIMEOUT_S` | `45` · `600` | Chat reply limits: until the intent is known, and for the whole reply |
| `LL_LOG_JSON` · `LL_LOG_LEVEL` | `true` · `INFO` | JSON logs for machines, `false` for readable console output |
| `LL_STANDIN_MODEL_OFFLINE` · `LL_STANDIN_FAIL_MIDSTREAM` · `LL_STANDIN_TOKEN_DELAY_MS` | `false` · `false` · `20` | Simulate a model outage, a mid-answer failure, or a slower model |

## API at a glance

Every error has the same body, `{ "code", "message", "request_id" }`, and every response carries an `X-Request-ID` header. The full schemas are in [openapi.json](openapi.json) and at `/api/docs` while the server runs.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | `{status, modelRuntime, model}` |
| GET · POST | `/api/documents` | Library (newest first) · upload (multipart field `file`) |
| GET · DELETE | `/api/documents/{id}` | Status (the UI polls this during ingestion) · delete everything derived from the document |
| POST | `/api/documents/{id}/retry` | Re-run ingestion for a failed document |
| GET | `/api/documents/{id}/pages/{n}` | Extracted text of one page (Source Viewer) |
| GET · POST | `/api/conversations` | List (most recent first) · create |
| GET · PATCH · DELETE | `/api/conversations/{id}` | Open with messages and citations · rename or relink · delete |
| POST | `/api/chat/stream` | Send a message. The reply streams as SSE: `intent → status* → token* → citation* → done`, or `error` |

```bash
# upload, then poll until "status": "ready"
curl -F "file=@Mutual_NDA.pdf" http://127.0.0.1:8000/api/documents
curl http://127.0.0.1:8000/api/documents/<doc_id>

# chat (-N shows events as they arrive)
curl -X POST http://127.0.0.1:8000/api/conversations -H "Content-Type: application/json" -d "{}"
curl -N -X POST http://127.0.0.1:8000/api/chat/stream -H "Content-Type: application/json" \
  -d '{"conversation_id":"<conv_id>","message":"How long does the NDA last?","document_ids":["<doc_id>"]}'
```

## How the code is organised

```
src/legallens/
  main.py, container.py   app factory, lifespan, wiring
  config.py               all settings (LL_* env vars)
  api/                    routes, schemas (mirror frontend/src/api/types.ts), errors, middleware, SSE
  services/               DocumentService, ConversationService, ChatService, TransactionLogger
  ingestion/              upload validation (by content, not extension) and the background job runner
  storage/                local file store (data/uploads/{doc_id}/original.pdf|docx)
  db/                     SQLAlchemy models, async engine, Alembic migrations (run on startup)
  ports/                  the interfaces the AI layer implements
  adapters/standin/       rule-based stand-ins for those interfaces
```

- **Chat:** `ChatService` saves the user message and an empty assistant message, then relays the orchestrator's events as SSE.
  - The reply is saved as `complete`, `stopped` (the client disconnected, for example by pressing Stop) or `error`.
  - After a crash, replies left `streaming` are marked as errors on the next start.
- **Ingestion:** documents left `processing` by a crash are re-queued on the next start.

## Plugging in the AI layer (Phase 3)

Adapters implement `ChatOrchestrator` from [ports/orchestrator.py](src/legallens/ports/orchestrator.py) and `IngestionPipeline` from [ports/ingestion.py](src/legallens/ports/ingestion.py), each through a factory that takes `Settings`. Routes, services and the database don't change.

**AI ingestion (available now).** Scanned pages are OCR'd, then every document is chunked, embedded and indexed for hybrid search, all on this machine. Pipeline and design: [../ai/README.md](../ai/README.md#ingestion-loader-or-ocr-then-chunk--embed--store), decisions and measurements: [../ai/ingestion.todo.md](../ai/ingestion.todo.md).

```bash
uv sync --extra ai          # adds the AI layer (../ai) and its local models' runtimes
LL_INGESTION=legallens.adapters.ai_ingestion:create uv run legallens-api
```

- Scanned and mixed PDFs become **Ready** instead of failing. Pages read by OCR show the OCR badge and their confidence; low-confidence pages add a warning to the document.
- The index (chunks DB + embedded Qdrant) lives in `<LL_DATA_DIR>/ai/`. Deleting a document removes its chunks and vectors too (FR-5).
- The first upload downloads the embedding model (~0.3 GB) and the first scanned page the OCR models (a few MB), once; then everything runs offline.
- AI-layer settings are `LL_AI_*` (see [../ai/.env.example](../ai/.env.example)), e.g. `LL_AI_OCR_DPI`.
- The adapter is [adapters/ai_ingestion.py](src/legallens/adapters/ai_ingestion.py); it only translates between the port and `legallens_ai`.
- Large scans take time: the job timeout default is 30 minutes (`LL_INGESTION_TIMEOUT_S=1800`).
- After changing `../ai/pyproject.toml`, run `uv lock` here too: this lock file records the AI layer's dependencies.

**AI chat (Claude).** Every message goes to the AI layer's orchestrator: Claude Haiku 4.5 picks the intent, then the Ask (Sonnet 5.5, hybrid search over the AI index, cited), Summary (Sonnet, or Opus for long documents), Draft (Opus 5.5) or Clarify workflow answers, streamed through the same SSE events as the stand-in. Design and decisions: [../ai/orchestration.todo.md](../ai/orchestration.todo.md).

```bash
uv sync --extra ai
# in .env (or the environment):
LL_ORCHESTRATOR=legallens.adapters.ai:create_orchestrator
LL_INGESTION=legallens.adapters.ai:create_ingestion
ANTHROPIC_API_KEY=...       # or in ../ai/.env
uv run legallens-api
```

- ⚠️ **Privacy:** with AI chat on, each message and recent history go to Anthropic's API, plus the retrieved passages (Ask) or the whole document (Summary, Draft). Documents, the index and chat history stay on this machine; ingestion never calls an API. The UI says so (`/api/health` reports `"processing": "cloud"`).
- AI chat needs AI ingestion: it answers from the AI index (the backend refuses to start otherwise). `legallens.adapters.ai_ingestion:create` still works and shares the same index.
- At startup the search models load in the background (`/api/health`: `loading`, then `ready`; `unavailable` without an API key). Documents uploaded before AI ingestion was on are indexed then, from their stored page text (no re-OCR).
- Each message logs one `ai_turn` line: intent, models, tokens and per-step timings, never text.
- The adapter is [adapters/ai.py](src/legallens/adapters/ai.py). End-to-end check against the real API (~$0.25): `uv run pytest -m live -s`.

## Connecting the frontend

The frontend has a "backend" mode that proxies its relative `/api/...` calls here. From `frontend/`:

```bash
npm run dev:stack      # starts this backend and the UI together → http://localhost:5173
```

The frontend README has the details, under "Running against the real backend". Through a proxy there is no cross-origin traffic, so `LL_CORS_ORIGINS` only matters if a page on another origin calls the API directly.

Two kinds of test keep the sides in step:
- The contract tests in `tests/contract/` read `frontend/src/api/types.ts` and fail if the two sides drift apart.
- `npm run test:e2e:api` in `frontend/` drives the real UI against this backend.

`scripts/demo_documents.py` builds the synthetic documents that both the seed script and those e2e tests use.

## Deploying elsewhere

You can deploy in either of two ways.

**With uv (Windows, macOS, Linux):** copy the `backend/` and `ai/` folders side by side (the lock file refers to `../ai` even without the AI extra; `ai/data` is not needed), then run from `backend/`:

```bash
uv sync --locked --no-dev            # add --extra ai for the AI layer
LL_DATA_DIR=/path/to/data uv run legallens-api
```

All dependencies install from pre-built wheels; no compiler is needed.

**With Docker:** the whole app (frontend and backend) runs from `compose.yaml` in the project root: `docker compose up --build` there, then open http://127.0.0.1:8080. For the backend alone:

```bash
docker compose up --build        # uses backend/compose.yaml
```

The equivalent without Compose:

```bash
# from the repository root (the AI layer in ../ai is part of the build context)
docker build -f backend/Dockerfile -t legallens-backend .
docker run -p 127.0.0.1:8000:8000 -v legallens-data:/data legallens-backend
```

For an image with the AI layer, add `--build-arg LL_EXTRAS=ai` (with Compose: `LL_EXTRAS=ai docker compose up --build`) and set `LL_INGESTION=legallens.adapters.ai:create_ingestion` (plus `LL_ORCHESTRATOR=legallens.adapters.ai:create_orchestrator` and `ANTHROPIC_API_KEY` in `.env` for Claude chat; `../ai/.env` is not in the image). Models then download into `/data/models` on first use.

The image is multi-stage, runs as a non-root user and has a health check. Data lives on the `/data` volume. Inside the container the app listens on `0.0.0.0`, but the port is published only on the host's `127.0.0.1`, so it is never reachable from the network.

## Development

```bash
uv run pytest                    # unit, integration, contract and BRD demo-path tests
uv run pytest --cov              # with coverage
uv run ruff format . && uv run ruff check .
uv run mypy                      # strict
uv run python scripts/export_openapi.py   # after an intended API change (refreshes openapi.json)
uv run alembic revision --autogenerate -m "describe change"   # after changing db/models.py
```

CI ([../.github/workflows/backend.yml](../.github/workflows/backend.yml)) runs these checks on Linux, Windows and macOS, and smoke-tests the Docker image.

## Troubleshooting

- **"Access is denied" from `uv` on Windows:** OneDrive is syncing `.venv` and locks its files. Usually the command still works on retry. To fix it for good, keep the environment outside OneDrive, for example `setx UV_PROJECT_ENVIRONMENT C:\venvs\legallens-backend`, then open a new terminal and run `uv sync`.
- **VS Code says packages aren't installed:** select the interpreter `backend/.venv` (*Python: Select Interpreter*).
- **Odd characters (`Â·`) in Windows PowerShell 5.1 output:** this is only how `Invoke-RestMethod` displays the text. The API sends UTF-8 JSON.
