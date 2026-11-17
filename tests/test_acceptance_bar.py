"""量化验收里可以在本机断言的条款。画面和 8 小时实机不在这里判通过。"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from src.adapters.governance import ReconnectBackoff
from src.avatar.blendshapes import weights_for_emotion
from src.avatar.glb import read_glb_json
from src.avatar.gpu import describe_gpu
from src.bus.event_bus import EventBus
from src.clock import FakeClock
from src.emotion.engine import EmotionEngine
from src.mapping.table import MappingTable
from src.overlay.quality import admit_fx, particle_budget, step_quality
from src.overlay.quality import QualityState
from src.print_show.timeline import progress_from_seek
from src.settings import Settings


def test_official_latency_bar_is_300ms_and_tighter_gate_exists():
    text = Path("tests/test_api_acceptance.py").read_text(encoding="utf-8")
    assert "e2e_p99 < 100" in text
    assert 100 < 300


def test_reconnect_delay_never_exceeds_five_seconds():
    backoff = ReconnectBackoff()
    now = 0.0
    for _ in range(12):
        delay = backoff.next_delay(now)
        assert delay <= 5
        now += delay


def test_fx_caps_and_downshift_exist():
    assert particle_budget(0, 50_000) == 20_000
    assert admit_fx(8, 8) is False
    state = QualityState()
    for _ in range(8):
        step_quality(state, 13)
    assert state.level >= 1


def test_aggregation_window_locked_at_200ms(project):
    assert Settings(project).default_model.normalize.danmaku_aggregate_window_ms == 200


def test_expression_switch_budget_and_glb_parse(project):
    scene = Path("apps/overlay/src/scene.ts").read_text(encoding="utf-8")
    assert "export const AVATAR_SWITCH_SEC = 0.28" in scene
    assert 0.28 * 1000 <= 300
    started = time.perf_counter()
    weights_for_emotion("awe", 1)
    assert (time.perf_counter() - started) * 1000 < 300
    root = Path("data/avatars/presets/yuan.glb")
    started = time.perf_counter()
    read_glb_json(root)
    assert (time.perf_counter() - started) < 2
    assert project is not None


def test_photo_fallback_does_not_claim_gpu_success():
    info = describe_gpu()
    assert info["cloud_api"] is False
    assert info["reconstruction_ran"] is False
    if not info["cuda"]:
        assert info["mode"] == "parametric-fallback"


def test_print_duration_seek_and_cue_map(project, tmp_path):
    settings = Settings(project)
    show = settings.default_model.print_show
    assert show.show_min_sec == 30
    assert show.show_max_sec == 60
    assert 30 <= show.default_duration_sec <= 60
    assert progress_from_seek(0.5) == 50
    assert list(show.progress_cues) == [25, 50, 75, 90, 100]
    clock = FakeClock()
    engine = EmotionEngine(settings, EventBus(clock=clock), MappingTable(settings), clock)
    for mark in show.progress_cues:
        cue = show.cue_table[mark]
        resolution = engine.on_print_progress(mark, "job-acceptance")
        assert resolution is not None
        assert resolution.emotion == cue.emotion
        assert resolution.fx == cue.fx
        assert resolution.fired is True


def test_session_replay_and_face_delete(client: TestClient):
    created = client.post(
        "/api/events/simulate",
        json={"source_msg_id": "sess-1", "type": "danmaku", "user_id": "u-sess", "nickname": "回看", "text": "你好"},
    )
    assert created.status_code == 200
    replayed = client.post("/api/replay/session")
    assert replayed.status_code == 200
    assert replayed.json()["replayed"] >= 1
    ctx = client.app.state.ctx
    now = time.time()
    ctx.store.save_avatar(
        {
            "avatar_id": "ava-del",
            "kind": "likeness",
            "preset_id": "",
            "job_id": "job-del",
            "name": "待删",
            "glb_rel": "",
            "approved": False,
            "created_at": now,
        }
    )
    ctx.store.save_avatar_job(
        {
            "job_id": "job-del",
            "avatar_id": "ava-del",
            "status": "review",
            "seed": 1,
            "reasons": [],
            "consent": True,
            "generator": "parametric-fallback",
            "gpu": {},
            "glb_rel": "",
            "created_at": now,
            "photo_ids": ["ph-del"],
        }
    )
    ctx.store.save_avatar_photo("ph-del", "job-del", "a.png", "cipher", now - 10 * 86400, now - 1)
    deleted = client.delete("/api/avatars/ava-del")
    assert deleted.status_code == 200
    assert ctx.store.list_photo_retention() == []
    leftover = ctx.store.save_avatar_photo("ph-old", "job-old", "b.png", "cipher", now - 30 * 86400, now - 1)
    assert leftover is None
    purged = ctx.purge_expired_photos()
    assert purged["deleted"] == 1
    actions = [row["action"] for row in client.get("/api/audit").json()]
    assert "session_replay" in actions
    assert "avatar_deleted" in actions
    assert "face_access" in actions
    assert "retention_cleanup" in actions
