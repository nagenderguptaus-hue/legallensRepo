# AI layer — Phase 3d: wire the orchestrator and workflows into the backend's chat

> **Status:** ✅ built and tested (2026-10-14/15). Committed together with Phase 3c by the
> ingestion session (one combined commit on `ingestion`). Results and deviations: §8.
> **Builds on:** [TODO.md](TODO.md) (intent router) · [workflows.todo.md](workflows.todo.md)
> (Ask / Summary / Draft) · [ingestion.todo.md](ingestion.todo.md) (OCR + indexing, already
> wired into the backend's upload flow) · backend port
> [ports/orchestrator.py](../backend/src/legallens/ports/orchestrator.py).

## 1. Where things stand

```
POST /chat/stream ─► ChatService ─► ChatOrchestrator port ─► RuleBasedOrchestrator (stand-in, keyword rules)  ← today
                                                          └► AI orchestrator ─► router (Haiku) ─► Ask / Summary / Draft  ← this phase

upload ─► IngestionRunner ─► AI ingestion adapter ─► OCR / loader → chunk → embed → Qdrant + FTS5  ✅ (uncommitted, ingestion branch)
```

| Piece | Status |
|-------|--------|
| Intent router (`Orchestrator.route()`) | ✅ built, tested. Only *classifies*; doesn't run anything |
| Ask / Summary / Draft workflows | ✅ built, tested, evaluated. Same event shapes as the backend port |
| Clarify reply | ❌ the router can say `clarify`, but no code writes the reply |
| Router → workflow dispatch | ❌ only the CLI calls workflows directly |
| Backend adapter for chat | ❌ the backend still uses the stand-in (`LL_ORCHESTRATOR=standin`) |
| Shared index between chat and ingestion | ⚠️ `AIRuntime` exists, but each backend factory would build its own → embedded Qdrant would refuse the second one (folder lock) |
| Documents uploaded before AI ingestion was on | ❌ not in the index → Ask / Summary would fail with `document_not_indexed` |
| Model warm-up, health | ❌ first Ask would download ~2–4 GB of models mid-request; `/health` knows nothing about Claude |

## 2. How one turn will flow

```
POST /chat/stream {conversationId, message, documentIds}
  └► ChatService (unchanged: validation, history, persistence, SSE)
       └► AIChatOrchestrator.stream(ctx)                     backend/src/legallens/adapters/ai.py  (thin)
            ChatContext ──► OrchestratorRequest
            └► Orchestrator.stream(request)                  ai/src/legallens_ai/orchestrator.py
                 1. route: Haiku intent  (+ needs_document rule)   ──► IntentEvent   → SSE `intent`
                 2. dispatch:
                      needs_document → fixed "select a document" reply
                      clarify        → ClarifyWorkflow   (template + suggestions, no LLM)
                      ask            → AskWorkflow       (rewrite → hybrid retrieval → gate → Sonnet)
                      summary        → SummaryWorkflow   (whole doc → Sonnet / Opus)
                      draft          → DraftWorkflow     (Opus, optional reference doc)
                 3. workflow events ──► status / token / citation / done → SSE, unchanged
            AI errors ──► backend OrchestratorError / ModelUnavailableError (same codes)
```

The routing + dispatch logic lives in `ai/` (testable from the CLI without the backend); the
backend adapter only translates types. `ai/` still never imports the backend.

## 3. Decisions (please review)

### 3a. Integration

| # | Decision | Why | Alternative |
|---|----------|-----|-------------|
| O1 | **`Orchestrator.stream(request)`** in `ai/`: routes, then runs the matching workflow and yields `IntentEvent` first, then the workflow's events. `route()` stays for evals. Workflows share a small `Workflow` protocol (`run(request) -> events`). | You asked for "orchestrator → workflow". Keeps the AI layer runnable on its own (new CLI `legallens-ai chat`) and the backend adapter trivial. | Dispatch inside the backend adapter (puts AI logic in the backend). |
| O2 | **One backend module `adapters/ai.py`** with two factories, `create_orchestrator` and `create_ingestion`, sharing **one `AIRuntime` per data folder** (process-wide registry). `ai_ingestion:create` keeps working as an alias. | Embedded Qdrant locks its folder: chat and ingestion must use the same client. No change to the backend's adapter-loading mechanism (NFR-7). | Change `Container` to build one AI object for both ports (touches core wiring). |
| O3 | **Stand-in stays the default.** AI chat is turned on with `LL_ORCHESTRATOR=legallens.adapters.ai:create_orchestrator` (+ the existing `LL_INGESTION=…`), documented in `.env.example`, README and Compose. | Backend tests, CI and the Playwright e2e keep running offline and free. | Make AI the default (every CI run needs an API key and model downloads). |
| O4 | **AI chat requires AI ingestion.** If `LL_ORCHESTRATOR` is AI and `LL_INGESTION` is the stand-in, startup fails with a clear message. | With the stand-in ingestion nothing is ever indexed, so every Ask would fail. Failing at startup beats failing on every message. | Warn and continue. |
| O5 | **Backfill (Q2):** at startup, Ready documents missing from the index are indexed in the background **from the page text already in the database** (no re-OCR, document stays Ready). Asking about one before it's done → error event "This document is still being prepared for AI search. Try again in a minute." | Documents uploaded before the switch (or with an older embedding model) become usable without re-uploading. Page text is the same `PageText` the indexer takes. | b) Index on demand inside the chat request · c) Manual `reindex` command only. |
| O6 | **Model warm-up + health.** At startup a background task loads the embedder and reranker (downloading them on first run, NFR-11). `/health`: `unavailable` if `ANTHROPIC_API_KEY` is missing, `loading` while warming up, else `ready`; model label e.g. `Claude Sonnet 5.5 · Opus 5.5 · Haiku 4.5`. No API call in health checks. | First Ask otherwise blocks on a multi-GB download; the frontend already shows the `loading` state. Health is polled, so it must be free. | Lazy load on first use (status quo). |
| O7 | **Clarify (Q3):** a template reply, no LLM call. Wording depends on whether a document is selected; 3 suggestion chips (the frontend shows them for `clarify` only). | The router already spent one call deciding the message is unclear; a fixed, friendly reply is instant and predictable. | Haiku writes a tailored clarifying question (+1 call, ~1 s). |
| O8 | **Error mapping:** AI `model_unavailable` → backend `ModelUnavailableError` (503 before streaming starts, `error` event after). Every other AI `OrchestratorError` → backend `OrchestratorError` with the **same code and message** (502 / `error` event). Unknown exceptions → existing `internal_error`. | One error vocabulary end to end; AI messages already tell the user what to do (FR-24). | — |
| O9 | **Timeouts (Q4):** backend `LL_STREAM_FIRST_EVENT_TIMEOUT_S` 30 → **45 s** (router: 15 s × up to 3 attempts) and `LL_STREAM_TOTAL_TIMEOUT_S` 300 → **600 s** (Opus summary up to 300 s + first-use model loading; CPU reranking ~50 s on long docs). Stand-in unaffected. Backend's "local model" wording in timeout/unavailable messages made neutral. | Today's limits would cut off legitimate long summaries. | Keep defaults; set them only in `.env` when AI is on. |
| O10 | **Cancel = stop the model.** The adapter is an async generator, so when the user presses Stop, `ChatService` closes it and the in-flight Claude stream is cancelled (no tokens billed after Stop). Covered by a test. | Already how the port works; worth proving with the real stack. | — |
| O11 | **Persist `chunk_id`** on citations (the backend writes `None` today). DB column already exists; API shape unchanged. | Lets us trace a saved answer back to the exact chunk (debugging, evals, later: highlight in Source Viewer). | — |

### 3b. Observability and privacy

| # | Decision |
|---|----------|
| O12 | One structured log line per turn, **metadata only** (NFR-5/NFR-10): request id, intent, models used, input/output tokens per call, timing per step (route, rewrite, retrieval, rerank, first token, total), best rerank score, gate fired, chunks sent, citations, warnings (`uncited_answer`, `missing_section:*`, `invented_citation`, `truncated`). Never message, rationale or document text (the router's rationale paraphrases the message, so it's excluded). |
| O13 | ⚠️ Privacy is unchanged from what you approved (D2 / W38): message + history go to Anthropic for routing; chunks (Ask) or the whole document (Summary / Draft) for generation. Turning AI chat on in the backend makes this real for the app, so the README "Privacy" section says it plainly next to the switch. |

## 4. Gaps and opportunities in the AI layer

Found by reading the three phase TODOs, the BRD and the code. **Bold = proposed for this phase.**

| # | Gap | Source | Proposal |
|---|-----|--------|----------|
| G1 | **No clarify reply** | router D3, FR-22 | Build now (O7) |
| G2 | **No router → workflow dispatch** | TODO.md "Later" | Build now (O1) |
| G3 | **Shared runtime, warm-up, health** | workflows.todo §8 | Build now (O2, O6) |
| G4 | **Unindexed existing documents** | found in review | Build now (O5) |
| G5 | **Per-step timings / per-turn trace log** | NFR-10 | Build now (O12) |
| G6 | **No CI for `ai/`** | listed in all 3 TODOs | New workflow `.github/workflows/ai.yml`: ruff, mypy, offline pytest (fakes, no models, no key). Backend CI adds a job with `--extra ai` running the adapter tests with fake models |
| G7 | **Intent eval never recorded against real Haiku** | TODO.md "Later" (no saved result in `evals/results/`) | Run `legallens-ai eval` (~$0.15), save the result, fix any misses in the prompt |
| G8 | **Rewriter misses** ("Which section says so?" restates the answer; "And what about insolvency?" labelled standalone) | workflows.todo §8 | Add eval cases, one prompt pass, re-run `eval-rewrite` (~$0.10) |
| G9 | **No end-to-end test through the real backend** | found in review | Opt-in live test (`pytest -m live`, backend): upload the synthetic NDA → Ask (cited, right page) → follow-up → "not found" question → Summary (6 headings) → Draft (placeholders) → Stop mid-answer → delete document purges index. ~$0.30 per run |
| G10 | Router prompt caching | TODO.md "Later" | **Skip**: the prompt is ~2.2k tokens, under Haiku 4.5's 4,096-token cache minimum. Recorded |
| G11 | Long documents untested live (Opus summary path, > 60k tokens; retrieval over hundreds of chunks) | workflows.todo §8 | Later (Q5): add 1–2 public-domain long documents to evals (~$1–2 per run) |
| G12 | FR-14 staged (map-reduce) summary | BRD | Stays deferred (W29: 1M context covers NFR-3's 300-page limit) |
| G13 | Multi-query variants, parent/child chunks | BRD §5, W12 | Stay deferred until an eval shows a recall gap |
| G14 | Qwen3-Reranker gate unchecked on our Ask cases; CPU rerank latency (~50 s on long docs vs NFR-1's 10 s) | workflows.todo 3b.1 | Later: you asked to optimise speed later. The per-turn timing log (O12) gives the numbers |
| G15 | Multi-column OCR, DOCX images | ingestion.todo I3/I8 | Ingestion session's area; not touched here |

## 5. Questions (first option = my recommendation)

| # | Question | Options |
|---|----------|---------|
| Q1 | Git: the ingestion work is still uncommitted on branch `ingestion`, and another session was editing it ~15 min ago. Shared files (`runtime.py`, `container.py`, `ai_ingestion.py`, Compose, `.env.example`) overlap. | **a) Once ingestion is committed, branch `orchestration` off `ingestion` and work there** (I re-read shared files before each edit) · b) Work in the same tree now, commit only my files |
| Q2 | Documents not yet in the AI index? | **a) Background backfill at startup from stored page text** (O5) · b) Index on demand during the chat request · c) Manual `reindex` command only |
| Q3 | Clarify reply? | **a) Template + suggestions, no LLM** (O7) · b) Haiku writes it |
| Q4 | Raise backend stream timeouts to 45 s / 600 s? | **a) Yes, new defaults** (O9) · b) Only in `.env` when AI is on |
| Q5 | Which gaps in this phase? | **a) G1–G9** (≈ $0.60 of API for evals + live tests) · b) G1–G6 only (integration + CI, no API spend) · c) G1–G9 + G11 long-document evals (+$1–2) |

## 6. Plan

### Step 0 · Prep
- [x] ~~Branch per Q1~~ → **not yet**: the ingestion session asked to hold off (its work is uncommitted and it still edits shared files). Working in the same tree; `orchestration` branch once ingestion is committed. Files the ingestion session owns are left untouched (§8)
- [x] Baselines green before any change: `ai/` 135 passed, backend 96 passed
- [x] `ANTHROPIC_API_KEY` is read from `ai/.env` by absolute path, so the backend picks it up too

### Step 1 · AI layer: orchestrator runs workflows (G1, G2) ✅
- [x] `events.py`: `IntentEvent`, `OrchestratorEvent`
- [x] `workflows/clarify.py`: `ClarifyWorkflow` (O7)
- [x] `orchestrator.py`: `Orchestrator.stream()` = route → `IntentEvent` → needs_document reply / clarify / workflow; `TurnTrace` with `metadata()` (O12, G5)
- [x] ~~`runtime.py`~~ → new **`engine.py`** (`ChatEngine`) on top of `AIRuntime`: `warm_up()`, `status()`, `backfill()`, `stream()`. Deviation: `runtime.py` belongs to the ingestion session, so the new code sits beside it instead of inside it
- [x] `streams.py` + workflows / generation: every layer closes the stream it reads, down to the model's HTTP stream (O10)
- [x] CLI: `legallens-ai chat [--doc <id>]` (`cli_chat.py`)
- [x] 20 offline tests (`tests/test_chat_engine.py`)

### Step 2 · Backend adapter (O2–O4, O8, O10, O11) ✅ except the alias
- [x] `adapters/ai.py`: `AIStack` per AI data folder, `create_orchestrator`, `create_ingestion`, `AIChatOrchestrator` (health, stream, error mapping, per-turn `ai_turn` log line), backfill from stored page text, warm-up at startup
- [x] `adapters/ai_ingestion.py:create` → the shared stack's pipeline; both `LL_INGESTION` values work with AI chat, anything else fails at startup with a clear message (O4)
- [x] `Container.shutdown` closes the orchestrator too: done without touching `container.py`: the shared ingestion pipeline's `aclose()` closes the whole stack
- [x] `ChatService`: `chunk_id` saved with citations; error status comes from the error (`document_not_indexed` → 409, `model_unavailable` → 503); neutral "AI model" wording
- [x] Timeout defaults 45 s / 600 s (Q4) in `config.py` and `.env.example`
- [x] 14 integration tests (`tests/integration/test_ai_chat.py`): every intent over SSE, not-found gate, citation + `chunk_id` saved, router failure → 503 with nothing saved, model failure mid-answer → `error` event + saved as error, Stop closes the model stream, health loading → ready, missing key → unavailable, backfill makes an old document askable, 409 while backfilling, factories share one stack, O4 check
- [x] Backend suite green with the stand-in (contract + snapshot updated for `processing`, §8)

### Step 3 · Quality of the AI layer (G7, G8) ✅
- [x] Intent eval on real Haiku: **43/43** (`evals/results/intent_run1.json`), no prompt change needed
- [x] Rewriter: 4 new eval cases, prompt pass, **27/27** (was 24/27 on the new set); Ask follow-up cases 3/3, all three now rewritten

### Step 4 · End to end (G9)
- [x] Live test `backend/tests/live/test_ai_live.py` (opt-in: `uv run pytest -m live -s`)
- [x] Live run: passed (§8)
- [ ] Manual check in the app (frontend + backend with AI on): for you, steps in §9

### Step 5 · CI, Docker, docs (G6)
- [x] `.github/workflows/ai.yml` (Ubuntu + Windows: ruff, mypy, offline pytest). The backend workflow already installs `--extra ai`, so the new adapter tests run there
- [x] Backend Docker smoke test: third matrix entry with AI chat (no key in CI: health answers `unavailable`). ⚠️ Not run locally (no Docker on this laptop); CI checks it
- [x] Compose comments and `.env.example`: how to switch AI chat on, key in `backend/.env` (`ai/.env` is not in the image). No `environment:` passthrough, since an empty host variable would blank the `.env` value
- [x] READMEs: backend ("AI chat (Claude)" + privacy note), `ai/` ("In the app: chat", eval results, `legallens-ai chat`); `TODO.md` "Later" and `workflows.todo.md` §8 ticked
- [x] Results + deviations written here

## 7. Not in this phase
- G10–G15 above (each with its reason)
- Changing the API contract or frontend (none needed: same events, intents, outcomes)
- Making AI chat the default

## 8. Results, deviations, open items (2026-10-14)

### Evidence

| Check | Result |
|---|---|
| `ai/` offline suite | 159 pass (20 new) · ruff · mypy strict. The ingestion session's real-OCR test (`test_rapidocr_reads_a_rendered_scan_end_to_end`) failed once with an OpenCV native error under memory pressure and passed on rerun |
| Backend suite (stand-in default) | 110 passed, 1 skipped (the opt-in live test); 14 new AI-chat integration tests · ruff · mypy strict |
| Intent eval, real Haiku 4.5 | **43/43**, p50 1.7 s, ~$0.11 |
| Rewrite eval, real Haiku 4.5 | **27/27** after the prompt pass (24/27 before, on the same 27 cases) |
| Ask eval, follow-up cases | 3/3 correct and cited; all 3 rewritten (before: "And what about insolvency?" was treated as standalone) |
| Live end to end through the backend | **passed**: AI ingestion → Ask (cited, page 2) → follow-up (page 3) → not found (gate, no Sonnet call) → Summary (6 sections, 7 citations) → Draft (Opus, 6 citations) → Clarify → delete purges the index. The first attempt crashed natively inside `truststore`'s Windows certificate check while only 1.9 GB of 15.7 GB RAM was free (the OCR benchmark was running); the same TLS calls work alone, and the retry passed. Watch for it if it recurs |
| Frontend unit tests | 2 chat tests fail **with and without** this change (checked by stashing the diff): mock-streaming timing under heavy CPU load (the ingestion session's OCR benchmark was running). Not caused by this phase; worth a look |

API spend for this phase: ~$0.75 (plan said ~$0.60; the extra rewrite-eval runs went into D-6) (intent eval 0.11, five rewrite-eval runs ~0.25, Ask follow-ups 0.05, live runs ~0.2).

### Deviations from the plan

| # | Plan | Built | Why |
|---|---|---|---|
| D-1 | Warm-up / backfill / status inside `runtime.py` | New `engine.py` (`ChatEngine`) wrapping `AIRuntime` | `runtime.py` is owned by the ingestion session, which is still editing it. Composition keeps both sessions' work separate; nothing is lost |
| D-2 | "No API contract or frontend change needed" | **Additive contract change:** `Health.processing: "local" \| "cloud"` (types.ts, backend schema, OpenAPI snapshot, mocks). Frontend copy now depends on it | With Claude on, the UI said "Local model ready · Runs on this computer" and "Private · stays on this device", which became false. Cloud mode now says "Files stay on this device · AI in the cloud", with a tooltip saying what is sent. "Local model" wording replaced by "AI model" (banner, composer, status). Stand-in / local mode keeps its original privacy text |
| D-3 | Port unchanged | `OrchestratorError(status=…)`; `ModelUnavailableError` → 503 by itself | Lets an adapter pick the HTTP status for errors before streaming (409 for a document still being indexed) without `ChatService` knowing AI error codes |
| D-4 | Warm-up once at startup | Warm-up retried on each health check until it succeeds | Found in review: a failed first download would leave the UI blocked forever (it disables sending while the model is unavailable). Test added |
| D-5 | Live test as `pytest -m live` | As planned in the end (was `LL_LIVE_AI=1` until the ingestion session freed `backend/pyproject.toml`) | — |
| D-7 | — | Two fixes from the live run's traces: finished turns were logged `cancelled` (the backend closes the stream right after `done`), and timing keys were doubled (`retrieval_rerank_ms_ms`) | Test added for the first |
| D-6 | Rewriter prompt: rules only | Rules + two worked examples (source questions; "And what about X?") | The first fix made "And for extra users?" copy "250" from the answer 4/4 times; one more sentence with a non-eval example fixed it (3/3 runs). A test keeps eval questions out of the prompt, and caught one leak during the work |

### Edits to the ingestion session's files (applied 2026-10-15, after it finished)

- [x] `adapters/ai_ingestion.py:create` → `stack_for(settings).ingestion`; O4 accepts either value
- [x] `config.py`: 45 s / 600 s (Q4)
- [x] `backend/pyproject.toml`: `live` marker, deselected by default (D-5 resolved: `uv run pytest -m live -s`)
- [x] `.env.example`, Compose comments, backend Docker smoke job, READMEs, `TODO.md`, `workflows.todo.md`
- [ ] Commit: your decision (relayed by the ingestion session): **one combined commit** of Phases 3c + 3d on branch `ingestion`, made by the ingestion session after both full suites pass. The two can't be split cleanly (`ai/` was never committed and the phases import each other), so no separate `orchestration` branch (Q1 superseded)

### Still open (not in this phase)

- **Latency on CPU** (live run, laptop under load): router 1.6–1.9 s warm (5.5 s on the first, cold connection); hybrid search 0.8–6.6 s and reranking ~5 s even on a 3-page document; Ask first text 9.5–19.7 s; Summary first text 2.6 s; Draft (Opus, effort high) first text 14.7 s, done in 31 s; Clarify 1.6 s. NFR-1 asks for first text ≤ 10 s. You asked to optimise later; the `ai_turn` log line now has the per-step numbers to do it with.
- Frontend: the two pre-existing chat-test failures above; Prettier reports formatting drift in ~60 files that predates this phase.

## 9. Manual check (for you)

1. `cd backend && uv sync --extra ai` (once), then in `backend/.env`:
   `LL_ORCHESTRATOR=legallens.adapters.ai:create_orchestrator` and
   `LL_INGESTION=legallens.adapters.ai:create_ingestion` (the key is read from `ai/.env`).
   ⚠️ `uv sync` will modify `backend/.venv`; it was in use by other sessions during this work.
2. `uv run legallens-api`, and the frontend against it (`npm run dev:backend` or your usual command).
3. Sidebar shows "AI model starting…" then "AI model ready" with the Claude models in the tooltip, and "Files stay on this device · AI in the cloud".
4. Upload a PDF → Ready. Ask a question → intent badge "Ask", cited answer, click a citation → Source Viewer page. Follow-up with "it". Ask something not in the document → "I couldn't find this in the document." "Summarize this document" → six sections. "Draft a memo on …" → memo with placeholders, then "make it shorter". Type "hmm" → three suggestion chips. Press Stop mid-answer → reply saved as stopped.
5. The backend console shows one `ai_turn` line per message (intent, models, tokens, timings; no text).
