import pytest

from legallens.config import Settings
from legallens.main import run
from tests.conftest import RunApp, Running


async def test_health_ok(r: Running) -> None:
    res = await r.client.get("/api/health")
    assert res.json() == {
        "status": "ok",
        "modelRuntime": "ready",
        "model": "Stand-in (no AI) · rule-based",
    }


async def test_health_degraded_when_model_runtime_is_down(run_app: RunApp) -> None:
    async with run_app(standin_model_offline=True) as r:
        body = (await r.client.get("/api/health")).json()
        assert (body["status"], body["modelRuntime"]) == ("degraded", "unavailable")


async def test_request_id_is_reused_when_valid_and_replaced_when_not(r: Running) -> None:
    ok = await r.client.get("/api/health", headers={"X-Request-ID": "trace-123"})
    assert ok.headers["x-request-id"] == "trace-123"
    bad = await r.client.get("/api/health", headers={"X-Request-ID": "bad id\twith junk"})
    assert bad.headers["x-request-id"].startswith("req_")


async def test_unknown_route_and_wrong_method_use_the_envelope(r: Running) -> None:
    missing = await r.client.get("/api/does-not-exist")
    assert (missing.status_code, missing.json()["code"]) == (404, "not_found")
    wrong = await r.client.put("/api/documents")
    assert (wrong.status_code, wrong.json()["code"]) == (405, "method_not_allowed")


async def test_cors_allows_only_the_local_frontend(r: Running) -> None:
    allowed = await r.client.options(
        "/api/health",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    blocked = await r.client.options(
        "/api/health",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in blocked.headers


def test_refuses_to_bind_to_a_public_interface(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LL_HOST", "0.0.0.0")
    monkeypatch.delenv("LL_ALLOW_REMOTE", raising=False)
    with pytest.raises(SystemExit) as info:
        run()
    assert "loopback" in str(info.value)


def test_settings_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LL_MAX_UPLOAD_MB", "5")
    monkeypatch.setenv("LL_CORS_ORIGINS", '["http://example.local:3000"]')
    settings = Settings(_env_file=None)
    assert settings.max_upload_bytes == 5 * 1024 * 1024
    assert settings.cors_origins == ["http://example.local:3000"]
