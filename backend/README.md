# Legal Lens — Backend

FastAPI service for Legal Lens. It handles document upload and ingestion, conversation history, and the streamed chat API (Server-Sent Events). It runs entirely on `127.0.0.1` and stores everything in a local folder: the SQLite database and the uploaded files.

The AI layer (Phase 3) plugs in behind two interfaces. Until then the backend runs end to end with built-in **stand-ins**:
- **Ingestion stand-in:** extracts real text from PDF and DOCX files. There is no OCR, so scanned files fail with a clear message.
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

In a second terminal, load the demo data: a synthetic lease (PDF) and NDA (DOCX), a scan that fails (no OCR yet), and five conversations covering ask, not found, summary, draft, clarify and a deleted source. Everything goes in through the API, so this works against any running instance.

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

1. Implement `ChatOrchestrator` from [ports/orchestrator.py](src/legallens/ports/orchestrator.py) and `IngestionPipeline` from [ports/ingestion.py](src/legallens/ports/ingestion.py). Each needs a factory that takes `Settings`.
2. Point the config at them: `LL_ORCHESTRATOR=legallens_ai.chat:create` and `LL_INGESTION=legallens_ai.ingest:create`.

Routes, services and the database don't change. The `chunks` table and the `chunks_fts` (FTS5/BM25) index already exist for the pipeline to fill. Deleting a document clears both and calls `pipeline.purge()` for the vectors.

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

**With uv (Windows, macOS, Linux):** copy the `backend/` folder, then run:

```bash
uv sync --locked --no-dev
LL_DATA_DIR=/path/to/data uv run legallens-api
```

All dependencies install from pre-built wheels; no compiler is needed.

**With Docker:** the whole app (frontend and backend) runs from `compose.yaml` in the project root: `docker compose up --build` there, then open http://127.0.0.1:8080. For the backend alone:

```bash
docker compose up --build        # uses backend/compose.yaml
```

The equivalent without Compose:

```bash
docker build -t legallens-backend .
docker run -p 127.0.0.1:8000:8000 -v legallens-data:/data legallens-backend
```

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
