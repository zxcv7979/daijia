"""降档、断线罐头、上下文恢复、重连、保留期和人脸访问审计。"""

from __future__ import annotations

import time
from io import BytesIO

from PIL import Image
from fastapi.testclient import TestClient

from src.bus.event_bus import EventBus
from src.clock import FakeClock
from src.ops.alerts import adapter_problem
from src.ops.degrade import canned_frame, combine_quality, context_recovery_plan, load_level
from src.ops.metrics import budget_breaches
from src.ops.retention import cleanup_expired_photos
from src.overlay.quality import apply_load
from src.store import Store


def test_load_downshift_stacks_on_frame_budget():
    assert load_level(0.2, None) == 0
    assert load_level(0.9, None) == 1
    assert load_level(None, 0.96) == 2
    assert combine_quality(0, 1) == 1
    assert apply_load(1, cpu=0.97) == 2
    assert apply_load(0, cpu=None, gpu=None) == 0


def test_canned_animation_does_not_freeze_or_rebuild():
    frame = canned_frame(2)
    assert frame["freeze"] is False
    assert frame["black"] is False
    assert frame["rebuild_geometry"] is False
    assert frame["hud"] == "层层生长"


def test_context_loss_plan_restores_without_black_frame():
    plan = context_recovery_plan()
    assert plan["rebuild_renderer"] is True
    assert plan["dispose_scene_graph"] is False
    assert plan["per_frame_rebuild"] is False
    assert plan["black_screen"] is False
    assert plan["keep_progress"] is True


def test_context_loss_route_audits(client: TestClient):
    body = client.post("/api/overlay/context-loss")
    assert body.status_code == 200
    assert body.json()["black_screen"] is False
    actions = [row["action"] for row in client.get("/api/audit").json()]
    assert "alert_context_loss" in actions


def test_reconnect_replays_print_progress_inside_30s():
    clock = FakeClock()
    bus = EventBus(clock=clock)
    bus.publish("print_progress", {"progress": 10, "hud": "层层生长"})
    clock.advance(5)
    newer = bus.publish("print_progress", {"progress": 40, "hud": "层层生长"})
    missed, gap = bus.replay_since(0)
    assert gap is False
    assert missed[-1]["seq"] == newer["seq"]
    assert missed[-1]["data"]["progress"] == 40


def test_retention_dry_run_then_delete(tmp_path):
    store = Store(tmp_path / "ops.db")
    try:
        now = time.time()
        store.save_avatar_photo("old", "job", "a.png", "cipher", now - 20 * 86400, now - 1)
        store.save_avatar_photo("new", "job", "b.png", "cipher", now, now + 7 * 86400)
        preview = cleanup_expired_photos(store, now=now, retention_days=7, dry_run=True)
        assert preview["candidates"] == 1
        assert preview["deleted"] == 0
        assert len(store.list_photo_retention()) == 2
        done = cleanup_expired_photos(store, now=now, retention_days=7, dry_run=False)
        assert done["deleted"] == 1
        left = store.list_photo_retention()
        assert [row["photo_id"] for row in left] == ["new"]
    finally:
        store.close()


def test_face_access_audit_has_no_photo_bytes(client: TestClient):
    image = Image.new("RGB", (16, 16), (250, 250, 250))
    raw = BytesIO()
    image.save(raw, format="PNG")
    response = client.post(
        "/api/avatars/jobs",
        data={"consent": "true", "subject_is_minor": "false", "sensitive": "false"},
        files={"photos": ("too-bright.png", raw.getvalue(), "image/png")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["fallback_avatar_id"] == "preset-yuan"
    rows = client.get("/api/audit").json()
    face = [row for row in rows if row["action"] == "face_access"]
    assert face
    assert face[0]["detail"]["op"] == "store"
    assert "blob" not in face[0]["detail"]
    assert "too-bright" not in str(face[0]["detail"])


def test_mapping_and_print_are_audited(client: TestClient):
    current = client.get("/api/mappings").json()["yaml"]
    saved = client.put("/api/mappings", json={"yaml": current})
    assert saved.status_code == 200
    created = client.post("/api/print-jobs", json={"style": "cartoon", "avatar_type": "stylized", "duration_sec": 30})
    assert created.status_code == 200
    actions = [row["action"] for row in client.get("/api/audit").json()]
    assert "mapping_reloaded" in actions
    assert "print_trigger" in actions


def test_preset_only_and_mute(client: TestClient):
    changed = client.post("/api/ops/mode", json={"mute": True, "preset_only": True, "load_level": 1})
    assert changed.status_code == 200
    config = changed.json()
    assert config["mute"] is True
    assert config["preset_only"] is True
    assert config["load_level"] == 1
    blocked = client.post("/api/avatars/active", data={"avatar_id": "likeness-demo"})
    assert blocked.status_code == 409


def test_budget_and_official_stub():
    assert budget_breaches([{"rss_kb": 100, "fds": 10}, {"rss_kb": 200, "fds": 12}], rss_kb=500, fds=5) == []
    assert "rss" in budget_breaches([{"rss_kb": 100, "fds": 10}, {"rss_kb": 1000, "fds": 10}], rss_kb=50, fds=5)
    assert adapter_problem({"name": "official", "state": "degraded"}) is None
    assert adapter_problem({"name": "mock", "state": "down"}) == "mock:down"
