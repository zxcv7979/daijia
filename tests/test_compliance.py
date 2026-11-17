"""真实采集默认关闭。打开时写审计，官方适配器仍然不启动连接。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from src.adapters.official import OfficialAdapterStub


def test_official_stub_never_starts_and_has_no_client():
    stub = OfficialAdapterStub()
    import asyncio

    result = asyncio.run(stub.start())
    assert result["started"] is False
    source = Path("src/adapters/official.py").read_text(encoding="utf-8")
    for token in ("import httpx", "import requests", "douyin.com", "https://", "http://"):
        assert token not in source


def test_collection_defaults_off_and_audits_when_enabled(client: TestClient):
    assert client.get("/api/compliance").json()["collection_enabled"] is False
    opened = client.post("/api/compliance/collection", json={"enabled": True})
    assert opened.status_code == 200
    body = opened.json()
    assert body["collection_enabled"] is True
    assert body["audited"] is True
    assert body["official_adapter"]["started"] is False
    rows = client.get("/api/audit").json()
    assert rows[0]["action"] == "collection_enabled"
    assert rows[0]["detail"]["official_adapter"] == "disabled"
    root = Path(client.app.state.ctx.root)
    logfile = (root / "data" / "audit" / "audit.jsonl").read_text(encoding="utf-8")
    assert "collection_enabled" in logfile
    assert "不连接任何平台" in logfile
    again = client.post("/api/compliance/collection", json={"enabled": True})
    assert again.json()["audited"] is False
    assert len(client.get("/api/audit").json()) == 1
    closed = client.post("/api/compliance/collection", json={"enabled": False})
    assert closed.json()["collection_enabled"] is False
    assert client.get("/api/compliance").json()["collection_enabled"] is False


def test_startup_audits_when_config_already_enabled(project):
    path = project / "config" / "default.yaml"
    text = path.read_text(encoding="utf-8").replace("collection_enabled: false", "collection_enabled: true", 1)
    path.write_text(text, encoding="utf-8")
    from src.api.app import create_app

    app = create_app(project)
    with TestClient(app) as client:
        rows = client.get("/api/audit").json()
        assert any(row["action"] == "collection_enabled" and row["detail"]["source"] == "startup" for row in rows)
        assert app.state.ctx.official.start_calls == 0
        assert client.get("/api/health").json()["official_adapter"] == "disabled"
