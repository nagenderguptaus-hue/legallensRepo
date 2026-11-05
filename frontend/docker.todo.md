# Frontend Docker image: review and fixes

> **Status:** ✅ implemented 2026-10-28 (all §4 recommendations accepted). Guide: [DOCKER.md](DOCKER.md).
> Results in §6. Not committed.

## 1. What exists today

`frontend/Dockerfile`: `node:24-slim` runs `npm ci` and `npm run build:api` (typecheck + Vite
build with `VITE_USE_MOCKS=false`), then `nginxinc/nginx-unprivileged:1.29-alpine` serves the
files and proxies `/api` to the backend (then `nginx.conf`, now [nginx.conf.template](nginx.conf.template)). Compose
(`../compose.yaml`) builds it.

| Check (2026-10-28) | Result |
|---|---|
| Build | ✅ 34 s, **83 MB**, nginx 1.29.8 / Alpine 3.23 (Node 24.22.1 in the build stage) |
| Non-root | ✅ user `101` (numeric) |
| `/`, deep link `/c/abc`, `/healthz` | ✅ 200 / 200 / 200 |
| `/api` next to a container named `backend` (Compose) | ✅ proxied to the backend |
| `/api` with a plain `docker run` | ❌ **502**, and a DNS error in the log every 5 s |
| `docker stop` | ✅ 0.9 s, exit 0 |
| Mock Service Worker in the image | ✅ removed |

## 2. Problems found

| # | Problem | Effect |
|---|---|---|
| P1 | Backend address hard-coded: `http://backend:8000` | Works only where the backend container is called `backend` |
| P2 | DNS resolver hard-coded: `127.0.0.11` (Docker's embedded DNS) | Exists only on user-defined Docker networks: **on AKS `/api` fails permanently**, and a plain `docker run` logs errors |
| P3 | `proxy_read_timeout 360s`, comment says the backend's limit is 300 s | The backend's limit is now **600 s** (`LL_STREAM_TOTAL_TIMEOUT_S`): nginx would cut a long Draft answer after 6 min |
| P4 | Floating base tags `node:24-slim`, `nginx-unprivileged:1.29-alpine` | Builds change silently |
| P5 | No run guide; health check is static-only | — |

## 3. Proposed fixes

| # | Fix | Why |
|---|---|---|
| F1 | `nginx.conf` → `nginx.conf.template`; the backend address comes from **`BACKEND_URL`** at container start (default `http://backend:8000`, so Compose is unchanged) | One image for Compose, a plain `docker run` and AKS. The nginx image's entrypoint already fills templates from environment variables. |
| F2 | DNS resolver taken from the container's own `/etc/resolv.conf` (the nginx image's built-in `NGINX_ENTRYPOINT_LOCAL_RESOLVERS`) | Correct in Compose, on the default bridge and in Kubernetes, with no hard-coded IP |
| F3 | Proxy timeouts 660 s (backend limit 600 s + margin), also from env (`PROXY_READ_TIMEOUT`) | Long drafts aren't cut off |
| F4 | Pin `node:24.22.1-slim` and `nginx-unprivileged:1.29.8-alpine3.23` | Reproducible builds |
| F5 | `frontend/DOCKER.md`: build, run (alone, next to the backend on a Docker network, against a backend on the host via `host.docker.internal`), check, logs, shell, stop/clean up, decisions, AKS notes | Same as the backend guide |
| — | Keep: two stages, `npm ci` before copying the source, non-root nginx, `/healthz`, SSE settings (`proxy_buffering off`), cache headers, security headers | Already right |

## 4. Questions (recommended option first)

| # | Question | Options |
|---|---|---|
| Q1 ✅ a | By "plain" image, do you mean keep nginx proxying `/api` to the backend, or a static-only image? | **a) Keep the proxy** (one origin for the browser: no CORS, the backend stays private, SSE tuned), with the backend address configurable (F1) · b) Static files only: the browser calls the backend directly. Needs the backend published to the browser, CORS, and a build-time API URL (the UI only calls relative `/api` today). |
| Q2 ✅ a | Also build a **mock-mode** variant (UI with fake data, no backend needed) for demos? | **a) No**, backend mode only (the mock build ships demo-only code) · b) Yes, as an opt-in build target `--target mock` |
| Q3 ✅ a | Base image for serving | **a) `nginxinc/nginx-unprivileged`** (today: non-root by default, 83 MB) · b) official `nginx` (runs as root by default; needs extra setup to drop root) · c) a Node server (bigger, slower for static files) |

## 5. Plan (after your answers)

- [x] F1–F4 in `Dockerfile` and `nginx.conf.template`
- [x] Build `legallens-frontend:local` (`--platform linux/amd64`); record size
- [x] Run and check: alone (UI 200, `/api` 502 without errors flooding the log), with the backend image on a Docker network (UI → `/api/health/ready` 200, upload a PDF, one chat stream), against a backend on the host; `docker stop` exit 0
- [x] `docker compose up --build` (full stack) still works
- [x] `frontend/DOCKER.md`; frontend README pointer; record results here

## 6. Results

| Check | Result |
|---|---|
| Build `legallens-frontend:local` (`--platform linux/amd64`) | ✅ 83 MB, user `101` |
| Rendered config | resolver = the container's DNS (`192.168.65.7` on the default bridge); `proxy_read_timeout 660s`; nginx's `$host`/`$uri` untouched |
| Alone (`docker run`, no backend) | UI 200, `/c/abc` 200, `/healthz` 200, `/api` 502; **no recurring DNS errors** (was one every 5 s) |
| Next to the backend image on a Docker network, `BACKEND_URL=http://legallens-backend:8000` | `/api/health/ready` 200 through nginx; PDF upload → Ready; chat streamed through nginx (`text/event-stream`, 21 token events, citation, done) |
| Backend on the host, `BACKEND_URL=http://host.docker.internal:8000` | ✅ `/api/health/live` 200 |
| `docker compose up --build` (full stack, repo root) | ✅ backend and frontend **healthy**, UI 200, `/api` ready: the first local run of the Compose stack (open in `../integration.todo.md` since Oct 6) |
| Container health / `docker stop` | healthy; 0.9 s, exit 0 |

**Not verified:** AKS (the full-name `BACKEND_URL` note is from nginx's documented behaviour, not
tested on a cluster), Apple Silicon.
