"""真实源默认关闭。二次确认才写审计；原文加密后可一键删除。"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient


def test_real_source_off_keeps_demo_and_blocks_silent_enable(client: TestClient):
    view = client.get("/api/compliance").json()
    assert view["real_source_active"] is False
    assert view["collection_enabled"] is False
    denied = client.post("/api/compliance/real-source", json={"enabled": True})
    assert denied.status_code == 400
    assert "二次确认" in denied.json()["detail"]
    assert client.get("/api/compliance").json()["real_source_active"] is False
    assert all(row["action"] != "real_source_enabled" for row in client.get("/api/audit").json())
    mock = client.post("/api/adapters/mock/start")
    assert mock.status_code == 200
    assert mock.json()["started"] is True
    official = client.post("/api/adapters/official/start")
    assert official.json()["started"] is False
    replay = client.post("/api/replay/start", json={"file": "replay.jsonl", "speed": 20, "loop": False})
    assert replay.status_code == 200
    client.post("/api/replay/stop")


def test_confirmed_real_source_audits_and_degrades(client: TestClient):
    opened = client.post("/api/compliance/real-source", json={"enabled": True, "confirm": True})
    assert opened.status_code == 200
    body = opened.json()
    assert body["real_source_active"] is True
    assert body["audited"] is True
    assert body["official_adapter"]["started"] is False
    assert body["official_adapter"]["state"] == "degraded"
    health = client.get("/api/adapters/official/health").json()
    assert health["alive"] is False
    assert health["degraded"] is True
    metrics = client.get("/api/adapters/official/metrics").json()
    assert metrics["events_pushed"] == 0
    rows = client.get("/api/audit").json()
    assert rows[0]["action"] == "real_source_enabled"
    assert "没有平台 I/O" in rows[0]["detail"]["note"]
    client.post("/api/compliance/real-source", json={"enabled": False, "confirm": True})
    assert client.get("/api/compliance").json()["real_source_active"] is False


def test_env_can_block_real_source(monkeypatch, client: TestClient):
    monkeypatch.setenv("REAL_SOURCE", "false")
    blocked = client.post("/api/compliance/real-source", json={"enabled": True, "confirm": True})
    assert blocked.status_code == 409
    assert client.get("/api/compliance").json()["real_source_active"] is False


def test_encrypted_raw_roundtrip_and_delete(client: TestClient):
    secret = "raw-secret-小明-42"
    created = client.post("/api/raw-payloads", json={"adapter": "mock", "payload": {"secret": secret}})
    assert created.status_code == 200
    assert secret not in created.text
    raw_id = created.json()["id"]
    listed = client.get("/api/raw-payloads").text
    assert secret not in listed
    assert "raw_ref" not in listed
    plain = client.app.state.ctx.read_encrypted_raw(raw_id)
    assert plain is not None
    assert secret in plain.decode("utf-8")
    deleted = client.delete("/api/raw-payloads")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] == 1
    assert client.get("/api/raw-payloads").json() == []
    blob = json.dumps(client.get("/api/events").json(), ensure_ascii=False)
    assert secret not in blob
