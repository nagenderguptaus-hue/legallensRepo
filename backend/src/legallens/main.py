"""Application factory and the ``legallens-api`` entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from legallens import __version__
from legallens.api.errors import install_error_handlers
from legallens.api.middleware import RequestContextMiddleware
from legallens.api.routes import api_router
from legallens.config import Settings
from legallens.container import build_container
from legallens.logging import configure_logging
from legallens.ports.ingestion import IngestionPipeline
from legallens.ports.orchestrator import ChatOrchestrator


def create_app(
    settings: Settings | None = None,
    *,
    orchestrator: ChatOrchestrator | None = None,
    pipeline: IngestionPipeline | None = None,
) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        container = await build_container(settings, orchestrator=orchestrator, pipeline=pipeline)
        app.state.container = container
        try:
            yield
        finally:
            await container.shutdown()

    app = FastAPI(
        title="Legal Lens API",
        version=__version__,
        description="Local-only backend for Legal Lens: documents, conversations and the "
        "streamed chat API. All errors use the envelope `{code, message, request_id}`.",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Accept", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestContextMiddleware)  # outermost: every response gets an id
    app.include_router(api_router)
    return app


def run() -> None:
    settings = Settings()
    configure_logging(settings.log_level, settings.log_json)
    if not settings.is_loopback and not settings.allow_remote:
        raise SystemExit(
            f"Refusing to listen on {settings.host!r}: Legal Lens only binds to loopback "
            "(127.0.0.1) so documents never leave this machine (NFR-5). Inside a container, set "
            "LL_ALLOW_REMOTE=true and publish the port on the host's 127.0.0.1 only."
        )
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        access_log=False,  # RequestContextMiddleware writes the access log as JSON
        server_header=False,
        proxy_headers=False,
        timeout_graceful_shutdown=10,
    )
