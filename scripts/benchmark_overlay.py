"""无头 Chrome 近似测量特效页帧率。不是 OBS，也不是独立显卡。

    python scripts/benchmark_overlay.py
    python scripts/benchmark_overlay.py --seconds 20 --rate 20

`--rate` 是每秒注入的模拟事件数。样本回放大约每秒 2 条，20 约等于 10 倍事件流。
真实 OBS 的数字见 docs/obs-browser-source.md，记为待实机验收。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import uvicorn
import websockets.sync.client as ws_client

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="特效页无头帧率近似")
    parser.add_argument("--seconds", type=float, default=12)
    parser.add_argument("--rate", type=float, default=20)
    parser.add_argument("--port", type=int, default=8791)
    args = parser.parse_args()
    dist = ROOT / "apps" / "overlay" / "dist" / "index.html"
    if not dist.is_file():
        sys.exit("先在仓库根目录执行 npm run build，特效页还没有 dist")

    from src.api.app import create_app

    app = create_app(ROOT)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="error"))
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{args.port}"
    _wait(f"{base}/api/health")

    chrome = _chrome()
    proc = subprocess.Popen(
        [
            chrome,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--no-first-run",
            "--user-data-dir=/tmp/overlay-chrome-profile",
            "--remote-debugging-port=9224",
            "--window-size=1920,1080",
            f"{base}/overlay/?preview=1&hud=1",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    samples: list[dict] = []
    try:
        _wait("http://127.0.0.1:9224/json")
        pages = json.load(urllib.request.urlopen("http://127.0.0.1:9224/json"))
        page = next((item for item in pages if item.get("type") == "page" and "overlay" in item.get("url", "")), None)
        if page is None and pages:
            page = next((item for item in pages if item.get("type") == "page"), pages[0])
        if not page or "webSocketDebuggerUrl" not in page:
            raise SystemExit(f"没有找到特效页调试目标: {pages}")
        with ws_client.connect(page["webSocketDebuggerUrl"], open_timeout=5) as debugger:
            debugger.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
            debugger.recv()
            deadline = time.time() + args.seconds
            index = 0
            next_event = time.perf_counter()
            interval = 1 / args.rate if args.rate else 1
            while time.time() < deadline:
                now = time.perf_counter()
                if now >= next_event:
                    _post(
                        f"{base}/api/events/simulate",
                        {
                            "source_msg_id": f"bench-{index}",
                            "type": "danmaku" if index % 4 else "gift",
                            "user_id": f"bench-{index}",
                            "nickname": "压测",
                            "text": "榜一" if index % 4 else "刷屏",
                            "gift_id": "local_rose",
                            "gift_name": "小花",
                            "price": 1 if index % 4 == 0 else 0,
                        },
                    )
                    index += 1
                    next_event = now + interval
                debugger.send(
                    json.dumps(
                        {
                            "id": 2 + index,
                            "method": "Runtime.evaluate",
                            "params": {"expression": "window.__overlayStats || null", "returnByValue": True},
                        }
                    )
                )
                raw = json.loads(debugger.recv())
                value = ((raw.get("result") or {}).get("result") or {}).get("value")
                if isinstance(value, dict) and value.get("fps"):
                    samples.append(value)
                time.sleep(0.25)
    finally:
        proc.terminate()
        server.should_exit = True
        thread.join(timeout=3)

    if not samples:
        sys.exit("没有采到帧率。确认本机有 Chrome，并且特效页已经构建。")
    fps = sorted(item["fps"] for item in samples)
    frame = sorted(item["frame_ms"] for item in samples)
    heaps = [int(item.get("heap") or 0) for item in samples if item.get("heap")]
    summary = {
        "seconds": args.seconds,
        "rate_per_sec": args.rate,
        "samples": len(samples),
        "fps_p50": fps[len(fps) // 2],
        "fps_min": fps[0],
        "frame_ms_p50": frame[len(frame) // 2],
        "frame_ms_p95": frame[min(len(frame) - 1, int(len(frame) * 0.95))],
        "downshifted_any": any(item.get("downshifted") for item in samples),
        "particles_max": max(int(item.get("particles") or 0) for item in samples),
        "fx_max": max(int(item.get("fx") or 0) for item in samples),
        "heap_first": heaps[0] if heaps else None,
        "heap_last": heaps[-1] if heaps else None,
        "renderer": samples[-1].get("renderer"),
        "obs": "待实机验收",
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _chrome() -> str:
    for candidate in ("/usr/local/bin/google-chrome", "/usr/bin/google-chrome", "chrome", "google-chrome"):
        if Path(candidate).is_file() or candidate in {"chrome", "google-chrome"}:
            return candidate
    sys.exit("找不到 Chrome")


def _wait(url: str) -> None:
    deadline = time.time() + 8
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=0.4)
            return
        except Exception:
            time.sleep(0.1)
    raise SystemExit(f"等不到 {url}")


def _post(url: str, payload: dict) -> None:
    data = json.dumps(payload).encode()
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(request, timeout=2)
    except Exception:
        return


if __name__ == "__main__":
    main()
