import asyncio
import os

from fastapi import APIRouter

from legallens.api.deps import ContainerDep
from legallens.api.schemas import Health
from legallens.ports.orchestrator import RuntimeHealth

router = APIRouter(tags=["system"])

RUNTIME_CHECK_TIMEOUT_S = 3


@router.get("/health", response_model=Health, summary="Service and model runtime status")
async def health(c: ContainerDep) -> Health:
    db_ok = await c.db.ping()
    storage_ok = os.access(c.settings.resolved_data_dir, os.W_OK)
    try:
        async with asyncio.timeout(RUNTIME_CHECK_TIMEOUT_S):
            runtime = await c.orchestrator.health()
    except Exception:
        runtime = RuntimeHealth(status="unavailable", model="unknown")
    healthy = db_ok and storage_ok and runtime.status == "ready"
    return Health(
        status="ok" if healthy else "degraded",
        model_runtime=runtime.status,
        model=runtime.model,
    )
