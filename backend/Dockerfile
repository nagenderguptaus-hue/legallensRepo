# syntax=docker/dockerfile:1
# Legal Lens backend image: multi-stage, locked dependencies, non-root, data on a volume.
# Built from the repository root, because the optional AI layer (ai/) is a path dependency:
#   docker build -f backend/Dockerfile -t legallens-backend .
#   docker build -f backend/Dockerfile --build-arg LL_EXTRAS=ai -t legallens-backend .  # + AI layer
#   docker run -p 127.0.0.1:8000:8000 -v legallens-data:/data legallens-backend
# With LL_EXTRAS=ai, set LL_INGESTION=legallens.adapters.ai_ingestion:create to use it. Its
# embedding models download into /data/models on first use, then everything runs offline.

# ---------------------------------------------------------------- build
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
# Optional extras of the backend package: "" (stand-in adapters only) or "ai".
ARG LL_EXTRAS=""
WORKDIR /src/backend

# Dependencies first, so code changes don't invalidate this layer. The AI layer's metadata is
# needed even without the extra: the lock file refers to it.
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

# ---------------------------------------------------------------- runtime
FROM python:3.12-slim AS runtime
RUN useradd --create-home --uid 10001 legallens \
    && mkdir /data && chown legallens:legallens /data
COPY --from=build --chown=legallens:legallens /app/.venv /app/.venv

# Inside the container the app must listen on 0.0.0.0; publish the port on the host's
# loopback only (127.0.0.1:8000:8000) so documents stay on this machine (NFR-5).
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    LL_HOST=0.0.0.0 \
    LL_ALLOW_REMOTE=true \
    LL_PORT=8000 \
    LL_DATA_DIR=/data

USER legallens
WORKDIR /home/legallens
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"]
CMD ["legallens-api"]
