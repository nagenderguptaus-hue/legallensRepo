# Running the backend in Docker

The image is built from [Dockerfile](Dockerfile) with the **repository root** as the build
context (the optional AI layer in `../ai` is a path dependency). Everything below was run and
checked on 2026-10-28 with Docker 29.9 (Docker Desktop 4.97, `linux/amd64`).

Commands are written for bash/zsh and run from the repository root (`LegalLens/`). In
PowerShell, replace `\` line continuations with a backtick, or put the command on one line.

## 1. Quick start

```bash
docker build --platform linux/amd64 -f backend/Dockerfile -t legallens-backend:local .
cp backend/.env.docker.example backend/.env.docker
docker run -d --name legallens --platform linux/amd64 -p 127.0.0.1:8000:8000 \
  --env-file backend/.env.docker -v legallens-data:/data legallens-backend:local
curl http://127.0.0.1:8000/api/health/ready
```

## 2. Three images from one Dockerfile

| Image | Build command (add to `docker build --platform linux/amd64 -f backend/Dockerfile`) | Size* | Models | First start |
|---|---|---|---|---|
| `legallens-backend:local` | `-t legallens-backend:local .` | 309 MB | none (stand-ins, no AI) | ~2 s |
| `legallens-backend:ai` | `--build-arg LL_EXTRAS=ai -t legallens-backend:ai .` | 1.03 GB | downloaded at runtime into the `/data` volume (~3.6 GB, needs internet) | minutes the first time; ~85 s after |
| `legallens-backend:ai-models` | `--build-arg LL_EXTRAS=ai --target with-models -t legallens-backend:ai-models .` | 4.4 GB of layers (Docker Desktop shows 6.8 GB on disk) | baked into the image (`/opt/models`) | ~8 s, works offline |

\* As `docker images` reports them on this machine.

**Apple Silicon:** `--platform linux/amd64` builds and runs the image AKS will use (x86 nodes),
under emulation, so it is slower on a Mac. For quick local work on a Mac, dropping the flag should
build a native `linux/arm64` image (not tested here); push only amd64 images to the registry.

## 3. Run it

Plain image (no AI):

```bash
docker run -d --name legallens --platform linux/amd64 \
  -p 127.0.0.1:8000:8000 --env-file backend/.env.docker \
  -v legallens-data:/data legallens-backend:local
```

AI image, models downloaded on first start into the volume. Put your key in
`backend/.env.docker` (`ANTHROPIC_API_KEY=...`) or pass a separate env file:

```bash
docker run -d --name legallens --platform linux/amd64 \
  -p 127.0.0.1:8000:8000 --env-file backend/.env.docker \
  -e LL_ORCHESTRATOR=legallens.adapters.ai:create_orchestrator \
  -e LL_INGESTION=legallens.adapters.ai:create_ingestion \
  -v legallens-data:/data legallens-backend:ai
```

Same, reusing the models you already downloaded for local development (no 3.6 GB download):
add `-e LL_AI_MODELS_DIR=/models -v "$PWD/ai/data/models:/models:ro"`.

AI image with baked models: same command with `legallens-backend:ai-models`; add
`--network none` to prove it needs no internet (chat itself does need Anthropic's API).

`-p 127.0.0.1:...` publishes the port on this computer only: documents never become reachable
from the network (NFR-5).

## 4. Environment variables

All optional; the template [.env.docker.example](.env.docker.example) lists every one with its
default. Copy it to `.env.docker` (git-ignored). Don't quote values in an `--env-file`.

| Variable | Default in the image | Needed when |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | AI image with AI chat. Pass at runtime, never at build time. |
| `LL_ORCHESTRATOR` / `LL_INGESTION` | `standin` | Set to the `legallens.adapters.ai:…` values to use the AI layer (AI image only) |
| `LL_PORT` | `8000` | Change together with `-p`; the health check follows it |
| `LL_HOST` / `LL_ALLOW_REMOTE` | `0.0.0.0` / `true` | Set by the image; don't change inside a container |
| `LL_DATA_DIR` | `/data` | Mount a volume here: SQLite DB, uploads, AI index, downloaded models |
| `LL_LOG_LEVEL` / `LL_LOG_JSON` | `INFO` / `true` | JSON lines on stdout |
| `LL_CORS_ORIGINS` | localhost:5173 | Only if a browser page on another origin calls the API directly |
| `LL_MAX_UPLOAD_MB`, `LL_MAX_PAGES`, `LL_MAX_DOCUMENTS`, `LL_MAX_MESSAGE_CHARS`, `LL_HISTORY_TURNS` | 25, 300, 100, 8000, 10 | Limits |
| `LL_INGESTION_TIMEOUT_S`, `LL_INGESTION_MAX_RETRIES`, `LL_INGESTION_RETRY_BACKOFF_S` | 1800, 2, 1.0 | Ingestion jobs |
| `LL_STREAM_FIRST_EVENT_TIMEOUT_S`, `LL_STREAM_TOTAL_TIMEOUT_S`, `LL_SSE_PING_INTERVAL_S` | 45, 600, 15 | Chat streaming |
| `LL_AI_MODELS_DIR` | `/data/models` (`/opt/models` in `ai-models`) | Where models are read from / downloaded to |
| other `LL_AI_*` | see [../ai/.env.example](../ai/.env.example) | Model choices, OCR settings |

## 5. Check that it works

```bash
curl -i http://127.0.0.1:8000/api/health/live    # 200 {"status":"alive"}: the process serves
curl -i http://127.0.0.1:8000/api/health/ready   # 200 when ready; 503 while models warm up
curl http://127.0.0.1:8000/api/health            # the UI's status line (always 200)
# OpenAPI docs in a browser: http://127.0.0.1:8000/api/docs
# A real call: upload a PDF, then list the library (status goes processing → ready)
curl -F "file=@frontend/e2e/.fixtures/Commercial_Lease_Agreement.pdf;type=application/pdf" \
  http://127.0.0.1:8000/api/documents
curl http://127.0.0.1:8000/api/documents
```

`docker ps` shows `(healthy)` once the readiness check passes.

## 6. Logs, shell, stop, clean up

```bash
docker logs -f legallens                     # JSON lines; probe calls are logged only when they fail
docker exec -it legallens sh                 # shell inside (runs as user "legallens")
docker stop legallens                        # SIGTERM → graceful shutdown in ~2 s
docker rm legallens                          # remove the container (data stays in the volume)
docker volume rm legallens-data              # delete the data: documents, DB, index, models
docker image rm legallens-backend:local      # remove the image
```

## 7. Decisions

| Choice | Why |
|---|---|
| `python:3.12.16-slim-trixie`, pinned to the patch version | Matches `.python-version`; slim Debian keeps glibc wheels (onnxruntime, OpenCV) working, which Alpine/musl would not; bumping it is a deliberate one-line change |
| Not pinned by digest | Patch updates stay a tag change; a digest pin would also block security fixes until bumped by hand |
| Multi-stage: uv in `build`, only `/app/.venv` copied to the runtime | No uv, caches or build files in the final image |
| `uv sync --locked`, not `--frozen` | Fails the build if `uv.lock` is stale instead of silently installing it |
| Dependency layer before source | Code changes rebuild in seconds; dependencies are re-installed only when the lock changes |
| Allow-list `Dockerfile.dockerignore` | Only `pyproject`/`uv.lock`/`README`/`src` of `backend/` and `ai/` can enter the image: no `.venv`, tests, caches, `.env`, `.git`, documents or models |
| Non-root user, numeric `USER 10001:10001` | Least privilege; a numeric user lets AKS verify `runAsNonRoot` |
| One uvicorn process, no workers setting | The ingestion queue runs in-process, and SQLite and embedded Qdrant allow one writer; scale by replicas only after moving state out (see §8) |
| Exec-form `CMD`, server is PID 1 | Gets SIGTERM directly; uvicorn drains requests (≤ 10 s) and the app closes the DB and the vector store |
| `HEALTHCHECK` on `/api/health/ready`, port from `LL_PORT`, 600 s start period | Healthy means "can take traffic"; the start period covers a first start that downloads models |
| Readiness ignores the hosted model's availability | An Anthropic outage shouldn't pull every pod out of service: documents keep working and chat reports the outage |
| Models at runtime by default, baked as an opt-in target | Runtime: ~1 GB image and models changeable by setting, but a slow first start that needs internet. Baked: starts in seconds offline and versions models with the image, at ~4.4 GB |
| Models fetched with the app's own settings (`legallens-ai prefetch-models`) | The baked models are exactly the configured ones; the same command can run in an AKS init container |
| `HF_HUB_OFFLINE=1` in `ai-models` | No calls to Hugging Face at startup when everything is already in the image |
| Bytecode compiled at build (`UV_COMPILE_BYTECODE`) | Faster start; the read-only image never writes `.pyc` files |

## 8. Notes for AKS later

- **Probes:** liveness `GET /api/health/live`, readiness `GET /api/health/ready` on port 8000.
  For the AI image without baked models, give readiness time (a startup probe or a long
  `failureThreshold`): the first start downloads ~3.6 GB.
- **State:** the image is stateless, **the app is not**: the SQLite DB, uploads, the AI index
  and (unless baked) the models live in `/data`. Use a PersistentVolumeClaim (`ReadWriteOnce`)
  and **1 replica**. Running several replicas needs Postgres, a Qdrant server
  (`LL_AI_QDRANT_URL`) and blob storage instead: not built yet.
- **Shutdown:** SIGTERM → clean exit in ~2 s; the default 30 s `terminationGracePeriodSeconds`
  is plenty. Ingestion jobs interrupted mid-way are re-queued on the next start.
- **Secrets:** `ANTHROPIC_API_KEY` from a Kubernetes Secret (or Key Vault) as an environment
  variable; nothing secret is in the image (checked with `docker history --no-trunc`).
- **Logs:** JSON on stdout, ready for Container Insights.
- **Architecture:** push `linux/amd64` images.

## 9. Not verified

- AKS itself (no cluster yet) and an Apple Silicon Mac (built and run on Windows/amd64 only).
- Once, the AI image exited with code 137 (SIGKILL) after logging a complete shutdown; 4 later
  stops exited 0 in ~2 s. It happens after the server has finished (the AI layer's threads at
  interpreter exit), so no request is lost, but it is not explained yet.
