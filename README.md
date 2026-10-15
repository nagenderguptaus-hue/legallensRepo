# Legal Lens

A private AI assistant for lawyers that runs **entirely on your own computer**. Upload a PDF or Word document, then:
- **ask** questions and get answers with clickable citations,
- **summarize** the document,
- **draft** a memo or case brief.

Client documents never leave the machine. Built as a class demonstration project, to production standards.

> Requirements: [LegalLens_BRD.md](LegalLens_BRD.md) · Architecture: [architecture/legal_lens_flow.png](architecture/legal_lens_flow.png)

![Answer with citation and highlighted source](frontend/docs/screenshots/02-answer-with-source.png)

## What's here

| Folder | What it is | Status |
|---|---|---|
| [frontend/](frontend/) | React 19 + Vite + TypeScript UI. It can run on its own against an in-browser mock API. | ✅ [plan](frontend/TODO.md) |
| [backend/](backend/) | FastAPI service: uploads and ingestion, conversation history (SQLite), streamed chat (SSE) | ✅ [plan](backend/TODO.md) |
| [ai/](ai/) | AI layer. Done so far: the orchestrator's intent router (Claude Haiku 4.5 via LangChain), standalone and not yet wired in. Still to come: retrieval (RAG), the Ask/Summary/Draft workflows, OCR. Until then the backend runs on rule-based **stand-ins** that quote the document directly. | 🚧 [plan](ai/TODO.md) |
| [compose.yaml](compose.yaml) | The whole app in Docker: nginx (UI + `/api` proxy) in front of the backend | ✅ [integration plan](integration.todo.md) |

## Running it

Prerequisites: [Node.js](https://nodejs.org/) 20+ and [uv](https://docs.astral.sh/uv/). uv installs the right Python by itself. Docker is needed only for the last row.

| Mode | Commands | Open |
|---|---|---|
| **Full app, development** | `cd frontend && npm install && npm run dev:stack`, then in a second terminal `cd backend && uv run python scripts/seed_demo.py` | http://localhost:5173 |
| UI only, mock data | `cd frontend && npm run dev` | http://localhost:5173 |
| Backend only | `cd backend && uv run legallens-api` (API docs at `/api/docs`) | http://127.0.0.1:8000 |
| **Full app, Docker** | `docker compose up --build`, then `cd backend && uv run python scripts/seed_demo.py --url http://127.0.0.1:8080` | http://127.0.0.1:8080 |

Everything listens on `127.0.0.1` only. In Docker, only the frontend port is published, and the backend is reachable only through it.

**Reset the demo data:** `uv run python scripts/seed_demo.py --fresh` (from `backend/`). This deletes every document and conversation, then loads the demo set again.

## Class demo script

Uses the seeded data: a commercial lease and an NDA, both Ready, a scanned exhibit that failed, and five sample conversations. All documents are synthetic.

1. **Ask.** Click **New chat**. The lease is selected. Ask *"Can the tenant terminate the lease early?"*, then click citation **[1]**: the Source tab opens page 3 with §5 highlighted.
2. **Follow-up:** *"How much written notice does that require?"*
3. **Not found:** *"Does the lease include a non-compete clause?"* The app says so instead of guessing.
4. **Summary:** *"Summarize this lease"* returns cited sections.
5. **Draft:** *"Draft a memo on my exit options"* returns a memo with amber `[CONFIRM: …]` and `[CITATION NEEDED]` placeholders to fill in.
6. **Upload:** drag any text PDF onto the window and watch the ingestion stages. The failed *Scanned_Exhibit_A.pdf* shows **Retry** and **Delete**. OCR arrives with the AI layer.
7. **Restart:** for this step, run the two halves in separate terminals: `uv run legallens-api` in `backend/` and `npm run dev:api` in `frontend/`. Stop the backend with Ctrl+C, and the app shows *"Can't reach the Legal Lens service"*. Start it again, and the app reconnects by itself with every conversation still there.
8. **Delete** the lease from the library. Its conversations show *"Source document deleted"*.
9. **Offline:** turn off Wi-Fi and repeat any step. Nothing needs the network (BRD NFR-4).

To show failures on purpose, start the backend with one of these settings:
- `LL_STANDIN_TOKEN_DELAY_MS=120`: a slow model, so there's time to press **Stop**
- `LL_STANDIN_FAIL_MIDSTREAM=true`: an answer that fails partway, followed by **Retry**
- `LL_STANDIN_MODEL_OFFLINE=true`: the model-unavailable banner

## Tests

| Where | Command | Covers |
|---|---|---|
| `backend/` | `uv run pytest` | Unit, integration, contract tests (read `frontend/src/api/types.ts`), the BRD demo path over HTTP |
| `frontend/` | `npm test` | Unit and component tests against the mock API |
| `frontend/` | `npm run test:e2e` | The BRD demo path in a real browser, mock API |
| `frontend/` | `npm run test:e2e:api` | The BRD demo path in a real browser **against the real backend** |

CI (`.github/workflows/`) runs all of these. It also builds both Docker images and smoke-tests the Compose stack, streaming a chat reply through nginx. The backend checks run on Windows, macOS and Linux.
