"""测量 HTTP 注入 -> WebSocket 回读的端到端延迟（本地演示，不连平台）。

    python scripts/measure_ws_readback.py [--n 200]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
import urllib.request

import websockets.sync.client

BASE = "http://127.0.0.1:8787"
WS = "ws://127.0.0.1:8787/ws"


def post_event(idx: int) -> dict:
    body = {
        "type": "danmaku",
        "user_id": f"u{idx}",
        "nickname": f"用户{idx}",
        "text": f"延迟测量 {idx}",
        "source_msg_id": f"meas-{idx}",
    }
    req = urllib.request.Request(
        f"{BASE}/api/events/simulate",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    args = ap.parse_args()

    ws = websockets.sync.client.connect(WS)
    hello = json.loads(ws.recv())
    latest_seq = hello["data"]["latest_seq"]

    latencies: list[float] = []
    pending: dict[str, int] = {}

    for i in range(args.n):
        t0 = time.perf_counter()
        post_event(i)
        pending[f"延迟测量 {i}"] = i
        # 收消息直到匹配到本条
        while True:
            raw = ws.recv()
            msg = json.loads(raw)
            if msg.get("kind") != "event":
                continue
            data = msg.get("data") or {}
            event = data.get("event") or {}
            ref = event.get("text")
            if ref in pending:
                t1 = time.perf_counter()
                latencies.append((t1 - t0) * 1000)
                del pending[ref]
                break

    ws.close()
    print(json.dumps({
        "n": len(latencies),
        "p50_ms": round(pct(latencies, 0.50), 3),
        "p95_ms": round(pct(latencies, 0.95), 3),
        "p99_ms": round(pct(latencies, 0.99), 3),
        "max_ms": round(max(latencies), 3),
        "pending_unmatched": len(pending),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
