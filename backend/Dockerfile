# syntax=docker/dockerfile:1
# Legal Lens backend image. Build from the repository root: the optional AI layer (ai/) is a
# path dependency of the backend. Full guide: backend/DOCKER.md.
#
#   docker build --platform linux/amd64 -f backend/Dockerfile -t legallens-backend:local .
#   docker build --platform linux/amd64 -f backend/Dockerfile --build-arg LL_EXTRAS=ai \
#     -t legallens-backend:ai .                                  # + AI layer (models at runtime)
#   docker build --platform linux/amd64 -f backend/Dockerfile --build-arg LL_EXTRAS=ai \
#     --target with-models -t legallens-backend:ai-models .      # + AI layer, models baked in
#   docker run --rm -p 127.0.0.1:8000:8000 -v legallens-data:/data legallens-backend:local
#
# Stages: build (uv installs locked dependencies) → base (slim, non-root runtime) → runtime
# (the default target: it is last). Only with --target with-models: models → with-models.

# Exact patch version of Debian 13 "slim" Python, matching .python-version (3.12).
ARG PYTHON_IMAGE=python:3.12.16-slim-trixie

# ---------------------------------------------------------------- build
FROM ${PYTHON_IMAGE} AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
# Optional extras of the backend package: "" (stand-in adapters only) or "ai".
ARG LL_EXTRAS=""
WORKDIR /src/backend

# Dependencies first, so source changes don't invalidate this layer. The AI layer's metadata is
# needed even without the extra: the lock file refers to it. --locked (not --frozen) fails the
# build if uv.lock and pyproject.toml disagree, instead of installing a stale lock.
COPY backend/pyproject.toml backend/uv.lock ./
COPY ai/pyproject.toml ai/README.md /src/ai/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project --no-install-package legallens-ai \
    ${LL_EXTRAS:+--extra $LL_EXTRAS}

COPY ai/src /src/ai/src
COPY backend/README.md ./
COPY backend/src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable ${LL_EXTRAS:+--extra $LL_EXTRAS}

# ---------------------------------------------------------------- base (runtime image)
FROM ${PYTHON_IMAGE} AS base
ARG LL_EXTRAS=""
ARG LL_VERSION=0.1.0
LABEL org.opencontainers.image.title="legallens-backend" \
      org.opencontainers.image.description="Legal Lens API (FastAPI). Extras: ${LL_EXTRAS}" \
      org.opencontainers.image.version="${LL_VERSION}"
RUN useradd --create-home --uid 10001 legallens \
    && mkdir /data && chown legallens:legallens /data
COPY --from=build --chown=legallens:legallens /app/.venv /app/.venv

# Everything at runtime comes from LL_* variables (backend/.env.docker.example). Inside a
# container the app must listen on 0.0.0.0; publish the port on the host's loopback only
# (-p 127.0.0.1:8000:8000) so documents stay on this machine (NFR-5). One process on purpose:
# the ingestion queue runs in-process and SQLite / embedded Qdrant allow one writer.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    LL_HOST=0.0.0.0 \
    LL_ALLOW_REMOTE=true \
    LL_PORT=8000 \
    LL_DATA_DIR=/data \
    LL_LOG_JSON=true

# Numeric, so Kubernetes can verify runAsNonRoot (a user name can't be checked).
USER 10001:10001
WORKDIR /home/legallens
VOLUME ["/data"]
EXPOSE 8000
# Readiness, not just liveness: 503 while the AI image's models warm up. The start period
# covers a first start that downloads ~3.6 GB of models; failures during it don't count.
HEALTHCHECK --interval=30s --timeout=5s --start-period=600s --retries=3 \
    CMD ["python", "-c", "import os, sys, urllib.request as u; p = os.environ.get('LL_PORT', '8000'); sys.exit(0 if u.urlopen(f'http://127.0.0.1:{p}/api/health/ready', timeout=4).status == 200 else 1)"]
# Exec form: the server is PID 1 and receives SIGTERM directly (graceful shutdown, ≤ 10 s).
CMD ["legallens-api"]

# ---------------------------------------------------------------- models (opt-in)
# Downloads the AI layer's local models (embedder, reranker, OCR: ~3.6 GB with the defaults)
# with the same settings the app uses. Needs --build-arg LL_EXTRAS=ai.
FROM build AS models
ENV PATH="/app/.venv/bin:$PATH" \
    LL_AI_MODELS_DIR=/opt/models
RUN legallens-ai prefetch-models

# ---------------------------------------------------------------- with-models (opt-in target)
# The AI image with its models baked in: starts fast and needs no internet, at the cost of a
# ~4.6 GB image. The models are read-only inside the image; the app never downloads them.
FROM base AS with-models
COPY --from=models --chown=legallens:legallens /opt/models /opt/models
ENV LL_AI_MODELS_DIR=/opt/models \
    HF_HUB_OFFLINE=1

# ---------------------------------------------------------------- runtime (default target)
# Last stage, so a plain `docker build` produces it; the model stages above are skipped.
FROM base AS runtime
