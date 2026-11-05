# Backend Docker image: review and hardening

> **Status:** ✅ implemented 2026-10-28 (all §4 recommendations accepted). Guide:
> [DOCKER.md](DOCKER.md). Results in §6, deviations in §7. Not committed.
> **Scope:** `backend/Dockerfile` for local `docker build` / `docker run`, ready for AKS later
> (no AKS manifests in this step).

## 1. Facts from the code (not guessed)

| Item | Value | Source |
|---|---|---|
| Python | 3.12 (`requires-python >=3.12`, `.python-version` 3.12); image today: 3.12.16 | `backend/pyproject.toml`, `backend/.python-version` |
| Dependency manager | uv 0.12.23, `uv.lock`; the AI layer is an optional extra (`--extra ai`, path dependency `../ai`) | `backend/pyproject.toml` |
| Entry point | `legallens-api` → `legallens.main:run` → uvicorn, one process, graceful shutdown 10 s | `backend/src/legallens/main.py` |
| Port / bind | `LL_PORT` (8000), `LL_HOST`; non-loopback needs `LL_ALLOW_REMOTE=true` | `backend/src/legallens/config.py` |
| State | `LL_DATA_DIR` (`/data` in the image): SQLite DB, uploads, and with AI the chunk DB, embedded Qdrant and models | `config.py`, `adapters/ai_ingestion.py` |
| Health | `GET /api/health`: JSON `status` ok/degraded, **always HTTP 200** | `api/routes/health.py` |
| Docs | `/api/docs` (Swagger), `/api/openapi.json` | `main.py` |
| Logs | structlog JSON to stdout (`LL_LOG_JSON=true`) | `logging.py` |
| Secrets | `ANTHROPIC_API_KEY`, AI image with AI chat only | `ai/src/legallens_ai/config.py` |
| Models (AI image) | downloaded at startup (warm-up) into `<LL_DATA_DIR>/models`: bge-large-en-v1.5 1.4 GB, bge-reranker-v2-m3 2.2 GB, RapidOCR tiny 6 MB ≈ **3.6 GB** | `ai/src/legallens_ai/config.py`, `ai/data/models` |

## 2. The existing Dockerfile, built and run

| Check | Result |
|---|---|
| Builds (`--platform linux/amd64`), plain / AI | ✅ 29 s / 43 s |
| Image size, plain / AI (no models) | **309 MB** / **1.03 GB** |
| Multi-stage, uv sync in builder, deps layer before source | ✅ |
| Non-root | ✅ uid 10001 `legallens`, owns `/data` |
| No secrets / data in the image | ✅ `backend/Dockerfile.dockerignore` is an allow-list (source + lock files only) |
| Logs to stdout | ✅ JSON lines |
| SIGTERM | ✅ `docker stop` → clean shutdown in 1.3 s, exit 0 (uvicorn is PID 1, exec-form CMD) |
| `/api/health`, `/api/docs`, `/api/documents` | ✅ 200 / 200 / 200 |
| Docker HEALTHCHECK | ✅ healthy |

## 3. Gaps against your requirements, and proposed fixes

| # | Gap | Proposed fix | Why |
|---|---|---|---|
| G1 | Base image floats (`python:3.12-slim` → resolved to 3.12.16 / Debian 13 today) | Pin `python:3.12.16-slim-trixie` in both stages | Reproducible builds; bumping the patch version becomes a deliberate change |
| G2 | No probe-friendly health: `/api/health` returns 200 even when degraded | Add **`/api/health/live`** (200 while the process serves) and **`/api/health/ready`** (200 only when DB + data dir are writable and the model runtime is ready, else **503**). `/api/health` stays as is for the UI. Docker HEALTHCHECK uses `ready`. | AKS liveness must not restart a pod that is only warming up (3.6 GB of models); readiness must keep traffic away until it can answer |
| G3 | HEALTHCHECK hard-codes port 8000 | Read `LL_PORT` | Changing the port would mark the container unhealthy |
| G4 | "Workers" not configurable | **Keep exactly 1 process** and document it; no `LL_WORKERS` | The ingestion queue runs in-process, embedded Qdrant locks its folder and SQLite allows one writer: a second worker would fail or corrupt state. Scale = 1 replica for now. |
| G5 | Image is stateless, the **app is not**: SQLite, uploads, Qdrant and models live in `/data` | Document: `/data` must be a volume (an AKS PersistentVolumeClaim, `ReadWriteOnce`), 1 replica | True horizontal scaling needs Postgres + a Qdrant server + blob storage: a later phase, flagged not built |
| G6 | Models download at first start (3.6 GB, needs internet, slow first start) | See Q2 | Trade-off below |
| G7 | No env template / run guide | Add `backend/.env.docker.example` (every variable, no secrets) and `backend/DOCKER.md` (build, run, verify, logs, shell, stop/clean up, decisions, AKS notes) | Your checklist |
| G8 | No image metadata | OCI labels (`org.opencontainers.image.title/source/version`) | Traceability in a registry |
| — | `.dockerignore` | Keep the allow-list `backend/Dockerfile.dockerignore` (it keeps out `.venv`, tests, caches, `.env`, `.git` and everything else) | Safer than a deny-list: new files stay out by default |

## 4. Open questions (recommended option first)

| # | Question | Options |
|---|---|---|
| Q1 ✅ a | `uv sync --frozen` (as you wrote) or `--locked` (today)? | **a) `--locked`**: fails the build if `uv.lock` and `pyproject.toml` disagree; `--frozen` silently installs a stale lock · b) `--frozen` |
| Q2 ✅ a | AI models: bake into the image or load at runtime? | **a) Runtime, into the `/data` volume (today), plus an opt-in build arg `LL_BAKE_MODELS=true`** that bakes them into the image for AKS/offline · b) runtime only · c) always baked |
| Q3 ✅ a | Verify the AI image for real? | **a) Yes**: run it with the models mounted read-only from `ai/data/models` (no 3.6 GB download), your key via `--env-file`, upload a PDF and ask one question (≈ $0.01) · b) Only check that it starts and reports healthy (no API call) |
| Q4 ✅ a | Pin the base image by digest too (`@sha256:…`)? | **a) No, tag pin only** (patch updates stay a one-line change) · b) Tag + digest (fully reproducible, but security fixes need a manual digest bump) |

**Q2 trade-off.**
- **Runtime download** keeps the image at about 1 GB and lets you change models with a setting. But the first start needs internet and takes minutes, and every new volume downloads the models again.
- **Baking** makes the AI image about 4.6 GB, so pulls are slower and AKS nodes need disk to cache it. In return it starts fast, works with no internet, and the models are versioned with the image.

## 5. Plan

- [x] Dockerfile: pin base (G1); HEALTHCHECK on `/api/health/ready` with `LL_PORT` and a start period that covers model warm-up (G2, G3); OCI labels (G8); optional `LL_BAKE_MODELS` (Q2 a); `uv sync` flag per Q1
- [x] Backend: `/api/health/live` and `/api/health/ready`, plus tests; update `openapi.json` (the contract test checks it)
- [x] `backend/.env.docker.example` and `backend/DOCKER.md`, with the exact build, run, verify, logs, shell and clean-up commands and the decisions with one line each
- [x] Build both variants with `--platform linux/amd64`, fix anything that breaks; record sizes
- [x] Run both: probes (live, ready, and 503 while not ready), `/api/docs`, one real API call per variant (plain: upload a PDF → Ready; AI: per Q3), SIGTERM shutdown, non-root, no secrets in `docker history`
- [x] Backend tests, ruff, mypy; compose files and CI still build (same Dockerfile path and args)
- [x] Report: final sizes, what couldn't be verified (e.g. AKS itself, Apple Silicon emulation)

## 6. Results

| Check | plain `:local` | AI `:ai` | AI + models `:ai-models` |
|---|---|---|---|
| Build (`--platform linux/amd64`) | ✅ | ✅ | ✅ (prefetch 106 s) |
| Size (`docker images`) | 309 MB | 1.03 GB | 6.81 GB on disk = 4.4 GB of layers (models 3.63 GB, venv 634 MB) |
| User | `10001:10001` | `10001:10001` | `10001:10001` |
| `/api/health/live` | 200 at once | 200 after 7 s | 200 |
| `/api/health/ready` | 200 | **503 `loading`** during warm-up → 200 after 81–87 s (models mounted from the host) | 200 after 7–9 s with **`--network none`** |
| Real call | PDF upload → Ready (5 pages); Ask → answered, 1 citation | PDF → Ready in 5 s; "What is the monthly base rent?" → "$4,500 … 3% yearly", 3 citations, 11 s (Claude) | — |
| SIGTERM (`docker stop`) | exit 0 in 1.3–2.0 s | exit 0 in 2.5 s (once 137, see §7) | exit 0 in 1.9–2.3 s ×3 |
| Health check with `LL_PORT=9000` | healthy | — | — |
| Data survives a restart (volume) | ✅ | — | — |
| Secrets in `docker history --no-trunc` | none | none | none |
| Probe calls in the logs | none (only failures are logged) | failures (503) logged | — |
| Backend suite | 115 passed, coverage 93.7%, ruff + mypy clean |||

## 7. Deviations and open points

| Plan | Built | Why |
|---|---|---|
| `LL_BAKE_MODELS` build arg | `--target with-models` | A Dockerfile can't set `LL_AI_MODELS_DIR` conditionally without leaving an empty value (which pydantic reads as the current folder). A separate last-but-one stage is clean, and BuildKit skips it unless asked. |
| — | `legallens-ai prefetch-models` CLI command | Downloads exactly the configured models with the app's own code; reusable by an AKS init container. |
| `USER legallens` (existing) | `USER 10001:10001` | Kubernetes can only verify `runAsNonRoot` for a numeric user. |
| OCI `image.source` label | Left out | The repository has no remote yet; I didn't invent a URL. `title`, `description`, `version` are set. |
| — | `.gitignore` exception `!.env.docker.example` | The repo ignores `.env.*`; the template must be tracked, a real `.env.docker` stays ignored. |
| — | Probe requests logged at debug unless they fail | Probes every few seconds would flood the JSON logs. |

**Open:** once, the AI image exited **137 (SIGKILL)** about 2 s after logging a complete shutdown;
4 later stops exited 0. The gap between "Finished server process" and the exit (~2 s) is the AI
layer's threads (ONNX runtime, thread pool) at interpreter exit. No request is affected, but it
is not explained yet. **Not verified:** AKS, Apple Silicon.
