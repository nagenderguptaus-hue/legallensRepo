# Running the frontend in Docker

One image: the production build of the UI (backend mode, no mock code) served by unprivileged
nginx, which also proxies `/api` to the backend, so the browser talks to a single origin (no
CORS, the backend stays private, streamed answers pass straight through). Built from
[Dockerfile](Dockerfile) with **`frontend/`** as the build context. Everything below was run and
checked on 2026-10-28 with Docker 29.9 (`linux/amd64`). The backend image has its own guide:
[../backend/DOCKER.md](../backend/DOCKER.md).

Commands are for bash/zsh. In PowerShell, replace `\` line continuations with a backtick.

## 1. Build

```bash
cd frontend
docker build --platform linux/amd64 -t legallens-frontend:local .
```

83 MB. Apple Silicon: `--platform linux/amd64` builds the image AKS will run (x86 nodes),
under emulation.

## 2. Run

The image needs to know where the backend is: **`BACKEND_URL`** (default `http://backend:8000`).

**Next to the backend image, on a Docker network** (the usual way):

```bash
docker network create legallens
docker run -d --name legallens-backend --network legallens \
  -v legallens-data:/data legallens-backend:local
docker run -d --name legallens-frontend --network legallens -p 127.0.0.1:8080:8080 \
  -e BACKEND_URL=http://legallens-backend:8000 legallens-frontend:local
# open http://127.0.0.1:8080
```

The backend needs no `-p` here: only nginx reaches it, over the private network.

**Against a backend running on your computer** (e.g. `uv run legallens-api` on port 8000):

```bash
docker run -d --name legallens-frontend -p 127.0.0.1:8080:8080 \
  -e BACKEND_URL=http://host.docker.internal:8000 legallens-frontend:local
```

On Linux add `--add-host=host.docker.internal:host-gateway`.

**The whole stack with Compose** (from the repository root): `docker compose up --build`, then
open http://127.0.0.1:8080. Compose names the backend service `backend`, which is the default.

## 3. Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `BACKEND_URL` | `http://backend:8000` | Where `/api` is proxied. Scheme, host and port; no path. |
| `PROXY_READ_TIMEOUT` | `660s` | How long nginx waits on a streamed answer. Keep it above the backend's `LL_STREAM_TOTAL_TIMEOUT_S` (600 s). |

Both are applied when the container starts (the nginx image fills
[nginx.conf.template](nginx.conf.template)); changing them needs a restart, not a rebuild. The UI
itself has no runtime settings and no secrets: it only calls relative `/api/...` URLs.

## 4. Check that it works

```bash
curl -i http://127.0.0.1:8080/healthz              # 200 "ok": nginx serves (no backend needed)
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/   # 200: the app
curl http://127.0.0.1:8080/api/health/ready        # the backend, through nginx
```

Then open http://127.0.0.1:8080 and upload a PDF. If the backend isn't reachable, the UI shows
"Can't reach the Legal Lens service" and reconnects by itself; nginx answers `/api` with 502 and
logs `backend could not be resolved` (or `connection refused`) for each such request.

## 5. Logs, shell, stop, clean up

```bash
docker logs -f legallens-frontend               # nginx access and error log
docker exec -it legallens-frontend sh           # shell (user 101); the live config is
                                                # /etc/nginx/conf.d/default.conf
docker stop legallens-frontend                  # SIGTERM → stops in ~1 s
docker rm legallens-frontend
docker image rm legallens-frontend:local
docker network rm legallens                     # after removing both containers
```

## 6. Decisions

| Choice | Why |
|---|---|
| nginx proxies `/api` (not a static-only image) | One origin for the browser: no CORS, the backend is never exposed, and the SSE settings live in one place |
| `nginxinc/nginx-unprivileged:1.29.8-alpine3.23` | Runs as numeric user 101 on port 8080 out of the box (Kubernetes `runAsNonRoot` works); Alpine is fine for static files and keeps the image at 83 MB |
| `node:24.22.1-slim` for the build only | Same major as development (Node 24); the build stage and its `node_modules` never reach the runtime image |
| Exact version tags, no digest | Reproducible builds; updating stays a one-line change |
| `npm ci --ignore-scripts` before copying the source | Locked install, no install scripts, and the dependency layer is cached across code changes |
| `npm run build:api` | Typecheck + Vite build in backend mode; the Mock Service Worker is removed from the output |
| Backend address and timeout from environment variables (nginx templates) | One image for Compose, a plain `docker run` and AKS |
| DNS server from the container's own `/etc/resolv.conf` | Works on Docker networks, the default bridge and Kubernetes; no hard-coded `127.0.0.11` (Docker-only) |
| Backend re-resolved every 10 s | nginx starts even when the backend is down and follows it across restarts |
| `proxy_buffering off`, 660 s timeouts | Chat tokens stream immediately; long drafts aren't cut off before the backend's own 600 s limit |
| `/healthz` answered by nginx itself | Liveness and readiness of the frontend don't depend on the backend |
| Hashed assets cached 1 year, `index.html` never cached | New releases show up immediately without stale code |

## 7. Notes for AKS later

- Probes: liveness and readiness `GET /healthz` on port 8080.
- `BACKEND_URL` = the backend Service's **full** DNS name, e.g.
  `http://legallens-backend.legallens.svc.cluster.local:8000`: nginx does not use DNS search
  domains, so a short name won't resolve.
- Stateless: any number of replicas.
- An ingress in front should also allow long-lived responses (SSE) and 26 MB uploads.
