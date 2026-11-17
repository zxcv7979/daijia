"""验收：零丢弃突发、场景、热路径延迟、WebSocket 补发与脱敏。"""

from __future__ import annotations

import asyncio
import json
import socket
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from websockets.sync.client import connect as ws_connect

from src.bus.metrics import _percentile
from src.runtime import build_context


def _wait_replay(client: TestClient, timeout: float = 5) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get("/api/replay").json()
        if not status["running"]:
            return status
        time.sleep(0.05)
    raise AssertionError(client.get("/api/replay").json())


def _read_until(ws, kind: str) -> list[dict]:
    messages = []
    while True:
        message = ws.receive_json()
        messages.append(message)
        if message["kind"] == kind:
            return messages


def test_two_hundred_concurrent_events_are_not_dropped(project):
    ctx = build_context(project)

    async def go() -> None:
        async def one(index: int) -> None:
            result = await ctx.ingest(
                {
                    "adapter": "sim",
                    "source_msg_id": f"peak-{index}",
                    "type": "like",
                    "user_id": f"peak-user-{index}",
                    "nickname": f"测{index}",
                    "raw_ref": f"sim:peak:{index}",
                }
            )
            assert result["ok"] is True
            assert result["op"] == "new"

        await asyncio.gather(*(one(index) for index in range(200)))

    try:
        asyncio.run(go())
        assert ctx.stats.received == 200
        assert ctx.stats.published == 200
        assert ctx.stats.dropped == 0
        assert ctx.stats.duplicates == 0
        assert ctx.store.count_events() == 200
        assert ctx.store.count_ingress() == 200
    finally:
        ctx.close()


def test_burst_endpoint_two_hundred_in_one_second(client: TestClient):
    response = client.post("/api/replay/burst", json={"count": 200, "window_sec": 1})
    assert response.status_code == 200
    body = response.json()
    assert body["requested"] == 200
    assert body["received"] == 200
    assert body["published"] == 200
    assert body["dropped"] == 0
    assert 0.85 <= body["elapsed_sec"] <= 3.0
    metrics = client.get("/api/metrics").json()
    assert metrics["dropped"] == 0
    assert metrics["latency_ms"]["p99"] < 100


def test_scripted_scenes(client: TestClient):
    names = {item["name"] for item in client.get("/api/scenes").json()}
    assert names == {"small_gift_combo", "big_gift_rank1", "danmaku_flood"}

    started = client.post("/api/scenes/start", json={"name": "small_gift_combo", "speed": 20})
    assert started.status_code == 200
    status = _wait_replay(client)
    assert status["scene"] == "small_gift_combo"
    assert status["emitted"] == 10
    gifts = [event for event in client.get("/api/events?limit=50").json() if event["type"] == "gift"]
    assert len(gifts) == 1
    assert gifts[0]["combo_count"] == 10
    assert gifts[0]["nickname_masked"] == "连**"
    assert client.get("/api/print-jobs").json() == []
    emotion = client.get("/api/emotion").json()
    assert emotion["emotion"] == "joy"

    client.post("/api/replay/stop")
    # 清空上一场打印和情绪的观察：新场景用独立断言。
    started = client.post("/api/scenes/start", json={"name": "big_gift_rank1", "speed": 20})
    assert started.status_code == 200
    _wait_replay(client)
    jobs = client.get("/api/print-jobs").json()
    assert any(job["style"] == "hologram" for job in jobs)
    emotion = client.get("/api/emotion").json()
    assert emotion["emotion"] == "awe"
    assert emotion["priority"] == 8

    client.post("/api/scenes/start", json={"name": "danmaku_flood", "speed": 20, "loop": False})
    _wait_replay(client)
    events = client.get("/api/events?limit=200").json()
    flood = [event for event in events if event["type"] in {"danmaku", "comment"}]
    assert len(flood) >= 10
    assert all(event["type"] in {"danmaku", "comment", "gift", "like", "enter", "follow", "combo"} for event in events)


def test_speed_and_loop_controls(client: TestClient):
    denied = client.post("/api/replay/speed", json={"speed": 3})
    assert denied.status_code == 422
    changed = client.post("/api/replay/speed", json={"speed": 5})
    assert changed.json()["speed"] == 5
    running = client.post("/api/replay/start", json={"file": "replay.jsonl", "speed": 20, "loop": True})
    assert running.status_code == 200
    assert running.json()["loop"] is True
    time.sleep(0.2)
    stopped = client.post("/api/replay/stop")
    assert stopped.json()["running"] is False
    assert client.get("/api/health").status_code == 200


def test_manual_levels_and_print_job(client: TestClient):
    for level, emotion in (("L0", "ambient"), ("L1", "ambient"), ("L2", "joy"), ("L3", "hype"), ("L4", "awe")):
        response = client.post("/api/trigger", json={"level": level})
        assert response.status_code == 200
        body = response.json()
        assert body["emotion"]["emotion"] == emotion
        assert body["fx_cue"]["level"] == level
        assert "raw_ref" not in json.dumps(body)
    created = client.post(
        "/api/print-jobs",
        json={"style": "hologram", "avatar_type": "stylized", "duration_sec": 0.4},
    )
    assert created.status_code == 200
    job_id = created.json()["job_id"]
    deadline = time.time() + 2
    job = created.json()
    while time.time() < deadline:
        job = client.get(f"/api/print-jobs/{job_id}").json()
        if job["status"] == "done":
            break
        time.sleep(0.05)
    assert job["status"] == "done"
    assert job["progress"] == 100


def test_ws_replays_missed_events_and_strips_pii(client: TestClient):
    simulated = client.post(
        "/api/events/simulate",
        json={
            "source_msg_id": "pii-1",
            "type": "danmaku",
            "user_id": "user-真实-42",
            "nickname": "小明",
            "text": "只留打码昵称",
            "raw_ref": "internal-secret-ref",
        },
    )
    assert simulated.status_code == 200
    with client.websocket_connect("/ws?since_seq=0") as websocket:
        messages = _read_until(websocket, "replay_done")
    blob = json.dumps(messages, ensure_ascii=False)
    assert "raw_ref" not in blob
    assert "internal-secret-ref" not in blob
    assert "user-真实-42" not in blob
    assert "小明" not in blob
    assert "小*" in blob
    assert any(item["kind"] == "event" and item["v"] == 1 for item in messages)
    stored = json.dumps(client.get("/api/events").json(), ensure_ascii=False)
    assert "user-真实-42" not in stored
    assert "internal-secret-ref" not in stored

    last_seq = max(item["seq"] for item in messages if isinstance(item.get("seq"), int))
    client.post("/api/trigger", json={"level": "L4"})
    with client.websocket_connect(f"/ws?since_seq={last_seq}") as websocket:
        replayed = _read_until(websocket, "replay_done")
    kinds = [item["kind"] for item in replayed]
    assert "fx_cue" in kinds
    assert "emotion" in kinds
    assert any(item["kind"] == "fx_cue" and item["data"]["level"] == "L4" for item in replayed)


def test_event_to_ws_latency_under_100ms(project, capsys: pytest.CaptureFixture[str]):
    from src.api.app import create_app

    app = create_app(project)
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    try:
        _wait_http(f"{base}/api/health")
        samples: list[float] = []
        with ws_connect(f"ws://127.0.0.1:{port}/ws?since_seq=-1", open_timeout=5) as websocket:
            hello = json.loads(websocket.recv(timeout=5))
            assert hello["kind"] == "hello"
            assert hello["data"]["buffer_sec"] == 30
            for index in range(30):
                started = time.perf_counter()
                response = httpx.post(
                    f"{base}/api/events/simulate",
                    json={
                        "source_msg_id": f"lat-{index}",
                        "type": "like",
                        "user_id": f"lat-user-{index}",
                        "nickname": "测速",
                    },
                    timeout=5,
                )
                response.raise_for_status()
                event_id = response.json()["event_id"]
                while True:
                    message = json.loads(websocket.recv(timeout=5))
                    event = (message.get("data") or {}).get("event") or {}
                    if message.get("kind") == "event" and event.get("event_id") == event_id:
                        break
                samples.append((time.perf_counter() - started) * 1000)
        metrics = httpx.get(f"{base}/api/metrics", timeout=5).json()
    finally:
        server.should_exit = True
        thread.join(timeout=5)

    queue_p50 = metrics["latency_ms"]["p50"]
    queue_p99 = metrics["latency_ms"]["p99"]
    e2e_p50 = _percentile(sorted(samples), 50)
    e2e_p99 = _percentile(sorted(samples), 99)
    print(
        f"LATENCY queue_p50={queue_p50:.3f}ms queue_p99={queue_p99:.3f}ms "
        f"e2e_p50={e2e_p50:.3f}ms e2e_p99={e2e_p99:.3f}ms n={len(samples)}"
    )
    assert metrics["dropped"] == 0
    assert queue_p99 < 100
    assert e2e_p99 < 100
    captured = capsys.readouterr()
    assert "LATENCY" in captured.out
    sys.stderr.write(captured.out)


def test_sample_files_cover_required_scenes():
    root = Path("data/samples")
    required = {
        "replay.jsonl",
        "scene_small_gift_combo.jsonl",
        "scene_big_gift_rank1.jsonl",
        "scene_danmaku_flood.jsonl",
    }
    assert required <= {path.name for path in root.glob("*.jsonl")}
    rank = (root / "scene_big_gift_rank1.jsonl").read_text(encoding="utf-8")
    assert "rank1" in rank
    flood = (root / "scene_danmaku_flood.jsonl").read_text(encoding="utf-8")
    assert flood.count("666666") >= 2


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_http(url: str) -> None:
    deadline = time.time() + 5
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            httpx.get(url, timeout=0.5).raise_for_status()
            return
        except Exception as exc:  # 服务还在启动
            last_error = exc
            time.sleep(0.05)
    raise RuntimeError(f"服务未就绪: {last_error}")
