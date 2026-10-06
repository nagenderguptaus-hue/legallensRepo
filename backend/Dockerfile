# syntax=docker/dockerfile:1
# Legal Lens backend image: multi-stage, locked dependencies, non-root, data on a volume.
#   docker build -t legallens-backend .
#   docker run -p 127.0.0.1:8000:8000 -v legallens-data:/data legallens-backend

# ---------------------------------------------------------------- build
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src

# Dependencies first, so code changes don't invalidate this layer.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

COPY README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

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
