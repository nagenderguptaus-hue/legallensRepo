"""Health endpoints.

- ``/api/health``: the UI's status line (always 200; ``status`` says ok or degraded).
- ``/api/health/live``: liveness probe. 200 whenever the process answers; no dependencies, so a
  slow database or a model warm-up never gets the container restarted.
- ``/api/health/ready``: readiness probe. 200 when this instance can take traffic, else 503.
"""

import asyncio
import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from legallens.api.deps import ContainerDep
from legallens.api.schemas import Health, Liveness, Readiness
from legallens.container import Container
from legallens.ports.orchestrator import RuntimeHealth

router = APIRouter(tags=["system"])

RUNTIME_CHECK_TIMEOUT_S = 3


async def _checks(c: Container) -> tuple[bool, bool, RuntimeHealth]:
    db_ok = await c.db.ping()
    storage_ok = os.access(c.settings.resolved_data_dir, os.W_OK)
    try:
        async with asyncio.timeout(RUNTIME_CHECK_TIMEOUT_S):
            runtime = await c.orchestrator.health()
    except Exception:
        runtime = RuntimeHealth(status="unavailable", model="unknown")
    return db_ok, storage_ok, runtime


@router.get("/health", response_model=Health, summary="Service and model runtime status")
async def health(c: ContainerDep) -> Health:
    db_ok, storage_ok, runtime = await _checks(c)
    healthy = db_ok and storage_ok and runtime.status == "ready"
    return Health(
        status="ok" if healthy else "degraded",
        model_runtime=runtime.status,
        model=runtime.model,
        processing=runtime.processing,
    )


@router.get("/health/live", response_model=Liveness, summary="Liveness probe")
async def live() -> Liveness:
    return Liveness(status="alive")


@router.get(
    "/health/ready",
    response_model=Readiness,
    summary="Readiness probe: 200 when ready, 503 when not",
    responses={503: {"model": Readiness, "description": "Not ready to take traffic"}},
)
async def ready(c: ContainerDep) -> Readiness | JSONResponse:
    db_ok, storage_ok, runtime = await _checks(c)
    is_ready = db_ok and storage_ok and runtime.status != "loading"
    body = Readiness(
        status="ready" if is_ready else "not_ready",
        database=db_ok,
        storage=storage_ok,
        model_runtime=runtime.status,
    )
    if is_ready:
        return body
    return JSONResponse(status_code=503, content=body.model_dump(by_alias=True))
