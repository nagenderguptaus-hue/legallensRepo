import json
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from legallens.config import Settings
from legallens.container import Container
from legallens.main import create_app
from legallens.ports.ingestion import IngestionPipeline
from legallens.ports.orchestrator import ChatOrchestrator
from tests.factories import make_pdf


@dataclass
class Running:
    app: FastAPI
    client: httpx.AsyncClient
    settings: Settings

    @property
    def container(self) -> Container:
        container: Container = self.app.state.container
        return container

    async def upload(
        self, content: bytes, name: str = "Mutual_NDA.pdf", content_type: str = "application/pdf"
    ) -> httpx.Response:
        return await self.client.post(
            "/api/documents", files={"file": (name, content, content_type)}
        )

    async def ready_document(
        self, content: bytes | None = None, name: str = "Mutual_NDA.pdf"
    ) -> dict[str, Any]:
        res = await self.upload(content or make_pdf(), name)
        assert res.status_code == 201, res.text
        await self.container.runner.wait_idle()
        doc = (await self.client.get(f"/api/documents/{res.json()['id']}")).json()
        assert doc["status"] == "ready", doc
        return dict(doc)

    async def new_conversation(self, **body: Any) -> dict[str, Any]:
        res = await self.client.post("/api/conversations", json=body)
        assert res.status_code == 201, res.text
        return dict(res.json())

    async def chat(
        self, conversation_id: str, message: str, document_ids: list[str] | None = None
    ) -> httpx.Response:
        return await self.client.post(
            "/api/chat/stream",
            json={
                "conversation_id": conversation_id,
                "message": message,
                "document_ids": document_ids or [],
            },
        )


def parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    events = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        name, data = "message", []
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].lstrip())
        if data:
            events.append((name, json.loads("\n".join(data))))
    return events


def make_settings(data_dir: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "data_dir": data_dir,
        "log_json": False,
        "log_level": "WARNING",
        "standin_token_delay_ms": 0,
        "ingestion_retry_backoff_s": 0,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


RunApp = Callable[..., AbstractAsyncContextManager[Running]]


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def run_app(data_dir: Path) -> RunApp:
    """``async with run_app(**settings, orchestrator=..., pipeline=...) as r:`` starts the
    app (lifespan included) against a private data dir."""

    @asynccontextmanager
    async def _run(
        *,
        orchestrator: ChatOrchestrator | None = None,
        pipeline: IngestionPipeline | None = None,
        **overrides: Any,
    ) -> AsyncIterator[Running]:
        settings = make_settings(data_dir, **overrides)
        app = create_app(settings, orchestrator=orchestrator, pipeline=pipeline)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                yield Running(app=app, client=client, settings=settings)

    return _run


@pytest.fixture
async def r(run_app: RunApp) -> AsyncIterator[Running]:
    async with run_app() as running:
        yield running
