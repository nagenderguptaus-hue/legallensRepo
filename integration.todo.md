# Legal Lens — Integration TODO (frontend ↔ backend)

> **Status:** ✅ implemented 2026-10-06 on branch `integration` (all §6 recommendations accepted). Everything runs green locally: backend 92 tests (93% coverage), frontend 50 unit/component tests, the mock e2e test, and 3 real-backend e2e tests. **Open:** the Docker images and the Compose stack are written but unbuilt, because Docker isn't installed on this laptop. CI builds and smoke-tests them on the first push (see §9).
> **Scope:** connect the existing React frontend ([frontend/](frontend/)) to the existing FastAPI backend ([backend/](backend/)). There is still no AI layer: the backend keeps its stand-in adapters. That is Phase 3 of the BRD.
> **Builds on:** [frontend/TODO.md](frontend/TODO.md) (done) · [backend/TODO.md](backend/TODO.md) (done, open items in §11) · contract source of truth: [frontend/src/api/types.ts](frontend/src/api/types.ts)

---

## 1. Approach in one paragraph

Both sides were built against the same contract, so integration should mostly be **wiring and verification, not rewriting**. The frontend already calls only relative `/api/*` URLs, MSW is switched off by `VITE_USE_MOCKS=false`, and the backend's contract tests already read `types.ts`. The plan has four parts:
1. **Wire** the frontend to the backend with a Vite proxy and a named "backend" mode. Mock mode stays the default, so the frontend still works on its own.
2. **Walk** every user flow through the real UI and fix whatever doesn't line up, adding a regression test for each fix.
3. **Lock it in** with an end-to-end Playwright test against the real backend, plus CI.
4. **Package** the full stack so it runs the same way on other machines (portability goal).

---

## 2. Where things stand (from reading both codebases)

### 2.1 Already lines up ✅
| Area | Evidence |
|---|---|
| Endpoints and paths | Every call in `frontend/src/api/*.ts` exists in the backend (`/api/health`, documents incl. `retry` and `pages/{n}`, conversations CRUD, `POST /api/chat/stream`) |
| Field names and casing | Backend `api/schemas.py` mirrors `types.ts`. `tests/contract/test_frontend_contract.py` fails on drift. |
| SSE events | Same events on both sides: `intent → status* → token* → citation* → done` or `error`. The frontend parser skips `: ping` comments. |
| Error envelope | `{code, message, request_id}` on both sides. The frontend toasts show `ref req_…`. |
| Ingestion stages | The stand-in emits `validating / extracting (n of N) / quality_check / chunking / indexing`, and every one of them has a label in `IngestionProgress.tsx` |
| Answer formats | `RuleBasedOrchestrator` is a port of the mock engine: summary `###` sections, memo/case-brief headers, `[CONFIRM: …]` / `[CITATION NEEDED]` placeholders |

### 2.2 Missing or at risk ⚠️
| # | Gap | Where |
|---|---|---|
| G1 | No Vite proxy and no npm script for "real backend" mode | `frontend/vite.config.ts`, `package.json` |
| G2 | The **Demo controls** dialog and the e2e test call `/api/__mock/*`, which the backend doesn't have (the dialog is already hidden when mocks are off) | `DemoControlsDialog.tsx`, `e2e/demo.spec.ts` |
| G3 | The e2e test asserts **mock-specific wording** (e.g. "early termination option", page 18) and uploads a fake PDF that the backend would rightly reject | `e2e/demo.spec.ts` |
| G4 | **Stop → send again** may hit `409 conversation_busy` if the backend hasn't noticed the disconnect yet | `useSendMessage.ts` ↔ `chat_service.py` |
| G5 | **Stop → refetch** may briefly return the reply as `streaming` (the backend marks it `stopped` only after it detects the disconnect) | same |
| G6 | Not yet proven: the dev proxy **streams SSE without buffering** and **passes the abort upstream** | Vite proxy |
| G7 | A browser that ran mock mode on `localhost:5173` keeps the **MSW service worker registered**. It should pass requests through, but this is unverified. | `main.tsx` |
| G8 | **Demo data:** the mock seed tells a story (5 documents, 7 conversations). The backend seed has 2 documents and 1 conversation. | `backend/scripts/seed_demo.py` |
| G9 | No way to run the **whole stack** with one command, and no frontend service in Compose | `backend/compose.yaml` |
| G10 | **No frontend CI** at all, and no CI job that runs both sides together | `.github/workflows/` |
| G11 | No top-level README that explains how the pieces fit and how to run them | `LegalLens/` |

**Can't be reproduced until the AI layer exists:** the mock's OCR states (*"OCR · page 7 of 12"*, "Ready with OCR warnings", the OCR badge in the Source Viewer). The backend has no OCR, so a scanned PDF **fails** with *"This looks like a scanned document. OCR arrives with the AI layer."* This is expected and gets documented, not fixed.

---

## 3. Run modes after integration

| Mode | Command | API served by | Use |
|---|---|---|---|
| UI only (unchanged) | `npm run dev` | MSW mocks in the browser | UI work, design demos, no Python needed |
| Full stack, dev | `npm run dev:stack` (or backend + `npm run dev:api` in two terminals) | FastAPI on `127.0.0.1:8000` through the Vite proxy | Day-to-day integrated development |
| Full stack, built | `npm run build:api && npm run preview:api` + backend | FastAPI through the preview proxy | Production-like local check, e2e tests |
| Full stack, Docker | `docker compose up --build` (in `LegalLens/`) | nginx → FastAPI, both containers | Other machines, class demo PC |

The proxy target comes from `VITE_API_TARGET` (default `http://127.0.0.1:8000`), so the backend can run on another port or host without code changes.

---

## 4. TODO — phased

### Phase 0 · Baseline
- [x] Get your approval of this TODO and answers to §6 (all recommendations accepted)
- [x] Create branch `integration`
- [x] Confirm both sides are green **before** touching anything (backend 92 tests, frontend 40 tests, all linters clean):
  - frontend: `lint`, `typecheck`, `test`, `build`
  - backend: `ruff`, `mypy`, `pytest`

### Phase 1 · Wiring (G1, G7)
- [x] `vite.config.ts`: `server.proxy` and `preview.proxy` send `/api` to `VITE_API_TARGET`, loaded with `loadEnv`
- [x] `frontend/.env.backend` (committed): `VITE_USE_MOCKS=false`. Mock mode stays the default (Q1). **Note:** the root `.gitignore` ignores `.env.*` as a secrets guard, so this one file gets a narrow exception. A backend-mode build goes to `dist-backend/` (preview port 4174), so it never overwrites the mock build, and it ships **no mock code** (the MSW chunk is tree-shaken out).
- [x] npm scripts:
  - `dev:api` = `vite --mode backend`
  - `build:api` / `preview:api` for the production build in backend mode
  - `dev:stack` starts the backend (`uv run --directory ../backend legallens-api`) and `dev:api` together, cross-platform (Q5)
- [x] `vite-env.d.ts`: type `VITE_USE_MOCKS` and `VITE_API_TARGET`
- [x] Real mode: if a leftover MSW service worker is registered, unregister it, so mocks can never answer by accident (G7)
- [x] Friendly first-run state when the backend isn't running. **Found and fixed:** F1, F3, F4 in §7.

### Phase 2 · Walk every flow through the real UI (G4–G6)
Run `dev:stack` against a **fresh data dir**, go through each row, and record ✅ or the bug found in §7.

**Done 2026-10-06.** Every row passes after the Phase 3 fixes. Most rows are now automated in `e2e/integration.spec.ts`. The env-flag rows (model offline, mid-stream failure, restart) were checked against throwaway backend instances and are also covered by backend integration tests.

| Area | Check |
|---|---|
| ✅ Health | Footer shows **Stand-in (no AI) · Ready**. Stop the backend → Unavailable, banner, sending disabled. Restart → recovers by itself. |
| ✅ Model offline | `LL_STANDIN_MODEL_OFFLINE=true` → `503 model_unavailable` → banner. Sending is blocked with an explanation. |
| ✅ Upload | PDF and DOCX → live stages with page progress → Ready, with no manual refresh. |
| ✅ Upload rejections | Client-side checks still fire first. Server-only errors show a clear toast: `duplicate_document`, `encrypted_file`, `unreadable_file`, `too_many_pages`, `library_full`. |
| ✅ Failed document | Scanned PDF → Failed with the "OCR arrives…" message → Retry → Failed again → Delete |
| ✅ Ask (F2 fixed) | Answer streams token by token (proves no proxy buffering, G6) with citation chips. Hover a chip → tooltip. Click it → Source Viewer opens on the right page with the quote **highlighted** (`<mark>`). |
| ✅ Not found | Unanswerable question → "Not found in the document" notice |
| ✅ Summary · Draft · Clarify | Summary card with sections. Draft card with the "N items need your input" badge. A short or vague message → clarify chips that send when clicked. |
| ✅ Needs document | New chat with no document selected → friendly reply, not an error |
| ✅ Conversations | First message auto-titles the chat. Rename, delete, search, date grouping. An unknown `/c/conv_x` URL → "Conversation not found". |
| ✅ Stop (G5 fixed) | Stop mid-answer → partial text kept. The backend log shows the disconnect (abort passed through the proxy). Reload → still `stopped`. Send again **immediately** → no `409`. |
| ✅ Mid-stream failure | `LL_STANDIN_FAIL_MIDSTREAM=true` → partial text, inline error, Retry works. Reload → the error is still shown with its `request_id`. |
| ✅ Delete document | Conversations that used it show "Source document deleted". Picking a new document clears the notice. |
| ✅ Restart | Kill the backend mid-answer, start it again → reload shows the reply as interrupted (`stream_interrupted`), not stuck "streaming". A document left processing is re-queued and finishes. |
| ✅ Request ids | A toast's `ref req_…` matches the `request_id` in the backend's JSON log line |

### Phase 3 · Fix what Phase 2 finds
- [x] Fix each mismatch on the side that breaks the contract (`types.ts` wins). Every fix gets a regression test on that side: a backend integration or contract test, or a frontend component test.
- [x] Likely fixes, confirmed or ruled out in Phase 2:
  - **G4 Stop → 409: ruled out.** The backend already releases the lock as soon as it sees the disconnect. Stop followed by an immediate send got 200 in 7 of 7 API probes and in the e2e test, so no retry was added.
  - **G5 Stop → stale `streaming`: confirmed** (1 in 6 probes) and fixed. See F5 in §7.
- [x] Remove any contract rough edges found. None needed a contract change: `types.ts` and `openapi.json` are unchanged.

### Phase 4 · Demo controls in real mode (G2)
Depends on Q2. Recommended option (B):
- [x] Keep the dialog **mock-only**, as it is now. In real mode the same scenarios come from the backend's env flags (`LL_STANDIN_TOKEN_DELAY_MS`, `LL_STANDIN_FAIL_MIDSTREAM`, `LL_STANDIN_MODEL_OFFLINE`).
- [x] Add a **"Reset demo data"** recipe to the README. **Changed:** `seed_demo.py --fresh` deletes everything through the API, then re-seeds. There's no need to stop the backend or touch the data folder, and it works against Docker too.

### Phase 5 · Demo data parity (G8)
- [x] Extend `backend/scripts/seed_demo.py` (synthetic content only, generated in code, uploaded **through the API** so it works against any deployment):
  - `Commercial_Lease_Agreement.pdf`: multi-page, with the clauses the demo script asks about (rent, term, early termination, default, indemnity)
  - `Mutual_NDA.docx`
  - one file that fails (e.g. a PDF with no text layer), to show Failed → Retry/Delete
  - conversations that cover ask with follow-up · not found · summary · draft memo · clarify · source deleted
  - **Note:** the documents live in `backend/scripts/demo_documents.py`, shared with the e2e fixtures. A fourth file, `Old_Engagement_Letter.pdf`, is uploaded, used in one chat, then deleted, to produce the "source deleted" conversation.
- [x] `--fresh` flag (refuses unless the target is loopback) and idempotent re-runs (skips existing duplicates, as it does today)
- [x] Update the class demo script (BRD §7) with questions that work against these documents. **Note:** the BRD itself only lists acceptance criteria and is unchanged. The script is in the new root [README.md](README.md#class-demo-script).

### Phase 6 · End-to-end tests against the real backend (G3)
- [x] Keep `e2e/demo.spec.ts` on **mocks**: a fast, deterministic UI test
- [x] Add a Playwright project `real-backend` with `e2e/integration.spec.ts`. **Note:** it is a separate config, `playwright.backend.config.ts`, because Playwright's `webServer` list is global rather than per project. The backend runs on port 8010, so the tests can run alongside `dev:stack`. 3 serial tests: empty library → needs document · the BRD path (+ shortened-quote highlight, server-side duplicate rejection) · DOCX + clarify + rename/search/delete + unknown conversation id.
  - `webServer` starts the backend with a **fresh temp `LL_DATA_DIR`** and `LL_STANDIN_TOKEN_DELAY_MS=40` (slow enough to click Stop), then `build:api && preview:api`. Both are health-checked before tests run.
  - Fixtures: a global setup writes the synthetic PDF/DOCX from `backend/tests/factories.py` to a temp folder (new `backend/scripts/make_fixtures.py`). No binaries are committed.
  - The flow asserts **structure, not mock wording**: upload → Ready → ask → citation chip → Source Viewer `<mark>` → unanswerable → not-found notice → summary card → draft with "need your input" → Stop → reload → still stopped → delete document → "Source document deleted". Plus: scanned PDF → Failed → Retry is visible.
- [x] Scripts: `test:e2e` (mocks, unchanged) and `test:e2e:api` (real backend)
- [x] Playwright browser selectable by env (`PW_CHANNEL`, default `msedge` locally, bundled Chromium in CI)

### Phase 7 · Full-stack packaging (G9, portability)
Depends on Q3. Recommended option (nginx):
- [x] `frontend/Dockerfile`: multi-stage, Node builds with `--mode backend` → `nginx-unprivileged` serves `dist/`
- [x] `frontend/nginx.conf` (also: Docker DNS re-resolution, so nginx starts and answers 502 → "service not reachable" while the backend is down, plus `/healthz` and basic security headers):
  - `/api` proxied to `backend:8000` with `proxy_buffering off` and `proxy_read_timeout 360s` (SSE)
  - `client_max_body_size 26m` (the 25 MB upload limit plus multipart overhead)
  - SPA fallback to `index.html`, long cache for hashed assets
- [x] `LegalLens/compose.yaml` (whole stack):
  - `frontend` published on `127.0.0.1:8080` only
  - `backend` **not published at all**: reachable only on the internal Compose network, which is even tighter than today for NFR-5
  - `depends_on: service_healthy`
  - the data volume carried over from `backend/compose.yaml`
- [x] `backend/compose.yaml` stays for backend-only use. **Note:** it uses its own data volume, separate from the full stack's.
- [x] Same origin through nginx, so no CORS changes are needed
- [ ] Docker isn't installed on this laptop, so the build is verified in CI (Phase 8), the same as the backend image today. **Open until the first push.**

### Phase 8 · CI (G10)
- [x] `.github/workflows/frontend.yml`: `npm ci` → lint → typecheck → test → build → e2e (mocks, Chromium). Runs on `frontend/**` changes.
- [x] `.github/workflows/integration.yml`: uv + Node → `uv sync --locked` → `npm ci` → `test:e2e:api`. Runs on `frontend/**` or `backend/**` changes. Uploads the Playwright trace on failure.
- [x] Compose smoke job (also checks the SPA fallback, an SSE reply streamed through nginx, and that port 8000 is **not** reachable from the host): `docker compose up -d --build`, then `http://127.0.0.1:8080/` serves the app and `http://127.0.0.1:8080/api/health` answers through nginx. Then tear down.

### Phase 9 · Docs and close-out (G11)
- [x] New `LegalLens/README.md`: what the project is, folder map, the run-modes table (§3), links to the BRD, the architecture diagram and each README
- [x] Update the frontend README ("Switching to the real backend") and the backend README ("Connecting the frontend", "Reset demo data") with the real commands
- [x] Close backend TODO §11 item 4 and frontend TODO DoD; set this file's status
- [ ] Optional, skipped: screenshots of the app running against the real backend for the class slides
- [x] Both sides green: frontend lint/typecheck/test/build/e2e (both projects), backend ruff/mypy/pytest

---

## 5. Out of scope
- The AI layer: LLM, RAG, OCR, embeddings. The stand-ins stay.
- Auth, multi-user, remote access (the app stays loopback-only, NFR-5)
- Generating TypeScript types from `openapi.json`. The existing contract tests already catch drift; revisit if the API grows.
- New UI features. Only fixes that integration needs.

---

## 6. Questions for your review (my recommendation first)

1. **Default mode for `npm run dev`.** **Recommended: keep mocks as the default** and add `dev:api` / `dev:stack` for the real backend. The frontend stays runnable without Python, which keeps the layers independent. The alternative makes the real backend the default and mocks opt-in (`dev:mock`).
2. **Demo controls with the real backend.**
   - **(B, recommended)** Keep the dialog mock-only and use the backend's env flags plus a reset recipe. Nothing new is added to the backend's API.
   - **(A)** Add dev-only `/api/__dev/settings` and `/api/__dev/reset` to the backend, enabled only by `LL_DEV_CONTROLS=true` (never in the Docker image). The same dialog then works live in both modes. This is nicer for a live class demo, but it adds a backend surface that has to stay locked down.
3. **How the built full stack is served.**
   - **Recommended: nginx container in front of the backend** (Phase 7). Each layer keeps its own image, and this is the standard production shape.
   - Alternative: FastAPI serves `frontend/dist` itself. That's one process and one port, but it couples the backend to the frontend build.
4. **Demo data.** **Recommended: extend `seed_demo.py`** to tell the same story as the mock seed (Phase 5), so the class demo looks the same in both modes. Alternative: keep the minimal seed. Also: synthetic documents (recommended, no licensing questions) or public-domain ones you supply?
5. **One-command start.** **Recommended: `npm run dev:stack`** using the small dev-only package `concurrently`, which works the same on Windows, macOS and Linux. Alternative: no new dependency, just two terminals as documented in the README.
6. **Git.** **Recommended:** work on a branch `integration` and commit at the end of each phase, so every phase can be reviewed and reverted on its own. Or I leave everything uncommitted for you to review.

---

## 7. Findings log (filled in during Phase 2)

| # | Flow | Found | Fixed in | Test |
|---|---|---|---|---|
| F1 | Backend down | Through a proxy (Vite, later nginx) a stopped backend answers **502 with no envelope**, so the UI said "unexpected problem" instead of "Is the backend running?" | `api/client.ts`: a bare 502/503/504 maps to `network_error` (an envelope, e.g. `503 model_unavailable`, still wins) | `api/client.test.ts` |
| F2 | Source Viewer | The stand-in shortens quotes over 300 characters with "…", so the exact-substring highlight found nothing on the page | `lib/quote.ts` `findQuote()` ignores a leading/trailing ellipsis; the highlight shows the page's own text | `lib/lib.test.ts`, e2e step 3 |
| F3 | Backend down | The banner said "the local *model* is unavailable… your documents and conversations are still available". Both parts were wrong when the whole service is down. | `ModelBanner`, `SidebarFooter`, `Composer` tell "service not reachable" apart from "model unavailable" | `app.test.tsx` › real backend conditions |
| F4 | Backend comes back | Health recovered by itself, but the library and conversation queries that failed stayed in their error state | `useRefetchAfterOutage()` in `AppShell` refetches every failed query when health recovers | same test |
| F5 (G5) | Stop / reload / 2nd tab | A server message still `streaming` with no local stream rendered as an empty body, and nothing refetched it | `MessageList` shows it as in progress; `useConversation` polls every 1 s until it settles | `app.test.tsx` › polls until it is done |
| — | Ask follow-ups | *Not a bug, a stand-in limit:* the rule-based follow-up only boosts with context words, so "How much notice does that require?" is not found. The AI layer's query rewriter (Phase 3) fixes this. | Demo seed uses "How much **written** notice does that require?" | — |
| — | Tooling | `prettier --check` already flagged 56 untouched files before this work. It isn't part of `lint`, so it was left alone. | — | — |

---

## 8. Definition of done
- `npm run dev:stack` gives a working app on `http://localhost:5173` backed by FastAPI and stand-ins, with no mock code loaded.
- `npm run dev` still runs the UI alone on mocks, unchanged.
- Every row in Phase 2 passes against the real backend.
- `test:e2e:api` runs the BRD §7 demo path against the real backend, locally and in CI.
- `docker compose up --build` in `LegalLens/` serves the whole app on `127.0.0.1:8080` (verified in CI).
- Both sides stay green: frontend lint/typecheck/test/build/e2e and backend ruff/mypy/pytest. The contract tests still pass.
- The READMEs explain every run mode.

---

## 9. Open items
1. **Push the repo to GitHub.** That runs the three workflows for the first time and builds both Docker images. The only unverified pieces are the `frontend/Dockerfile`, `nginx.conf` and the root `compose.yaml`.
2. Or **install Docker Desktop** (`winget install Docker.DockerDesktop`; needs WSL2 and a reboot), then run `docker compose up --build` in `LegalLens/` and `uv run python scripts/seed_demo.py --url http://127.0.0.1:8080` in `backend/`.
3. **Merge** branch `integration` into `main` when you're happy.
