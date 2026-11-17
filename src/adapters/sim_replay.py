"""JSONL 回放、剧本场景和 200 条/秒突发。速度可在运行中切换。"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Awaitable, Callable

from src.settings import Settings

logger = logging.getLogger("live_show.replay")

SCENES: dict[str, dict[str, str]] = {
    "small_gift_combo": {
        "title": "小礼物连击",
        "file": "scene_small_gift_combo.jsonl",
    },
    "big_gift_rank1": {
        "title": "大礼物榜一",
        "file": "scene_big_gift_rank1.jsonl",
    },
    "danmaku_flood": {
        "title": "弹幕刷屏",
        "file": "scene_danmaku_flood.jsonl",
    },
}

ALLOWED_SPEEDS = (1, 5, 20)
Ingest = Callable[[dict], Awaitable[dict]]


class SimReplay:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.ingest_cb: Ingest | None = None
        self.speed = settings.default_model.adapters.sim_replay.default_speed
        self.loop = settings.default_model.adapters.sim_replay.loop
        self.file: str | None = None
        self.scene: str | None = None
        self.running = False
        self.emitted = 0
        self._task: asyncio.Task[None] | None = None
        self._stop = False

    def status(self) -> dict[str, object]:
        return {
            "running": self.running,
            "file": self.file,
            "scene": self.scene,
            "speed": self.speed,
            "loop": self.loop,
            "emitted": self.emitted,
            "allowed_speeds": list(ALLOWED_SPEEDS),
        }

    def set_speed(self, speed: int) -> int:
        if speed not in ALLOWED_SPEEDS:
            raise ValueError("速度只允许 1、5、20")
        self.speed = speed
        return speed

    async def start_file(self, filename: str, *, speed: int | None = None, loop: bool | None = None, scene: str | None = None) -> dict[str, object]:
        path = self._resolve(filename)
        if speed is not None:
            self.set_speed(speed)
        if loop is not None:
            self.loop = loop
        await self.stop()
        rows = load_jsonl(path)
        self.file = path.name
        self.scene = scene
        self.emitted = 0
        self.running = True
        self._stop = False
        self._task = asyncio.create_task(self._play(rows))
        return self.status()

    async def start_scene(self, name: str, *, speed: int | None = None, loop: bool = False) -> dict[str, object]:
        try:
            meta = SCENES[name]
        except KeyError as exc:
            raise ValueError(f"未知场景 {name}") from exc
        return await self.start_file(meta["file"], speed=speed, loop=loop, scene=name)

    async def stop(self) -> dict[str, object]:
        self._stop = True
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self.running = False
        return self.status()

    async def burst(self, count: int = 200, window_sec: float = 1.0) -> dict[str, object]:
        """在 window_sec 内注入 count 条互不合并的模拟点赞。"""

        if count < 1 or count > 1000:
            raise ValueError("突发条数需要在 1 到 1000 之间")
        if window_sec <= 0 or window_sec > 10:
            raise ValueError("突发窗口需要在 0 到 10 秒之间")
        if self.ingest_cb is None:
            raise RuntimeError("回放器尚未绑定管线")
        nonce = uuid.uuid4().hex[:8]
        started = time.perf_counter()
        interval = window_sec / count
        for index in range(count):
            target = started + index * interval
            delay = target - time.perf_counter()
            if delay > 0:
                await asyncio.sleep(delay)
            await self.ingest_cb(
                {
                    "adapter": "sim",
                    "source_msg_id": f"burst-{nonce}-{index}",
                    "type": "like",
                    "user_id": f"burst-user-{nonce}-{index}",
                    "nickname": f"测{index}",
                    "price": 0,
                    "raw_ref": f"sim:burst:{nonce}:{index}",
                }
            )
        elapsed = time.perf_counter() - started
        return {"requested": count, "elapsed_sec": round(elapsed, 3)}

    async def _play(self, rows: list[dict]) -> None:
        assert self.ingest_cb is not None
        loop_index = 0
        try:
            while not self._stop:
                for row in rows:
                    if self._stop:
                        return
                    await _sleep_scaled(float(row.get("delay_ms") or 0), lambda: self.speed, lambda: self._stop)
                    if self._stop:
                        return
                    payload = {key: value for key, value in row.items() if key != "delay_ms"}
                    payload["adapter"] = "sim"
                    payload["ts"] = time.time()
                    if loop_index > 0 and payload.get("source_msg_id"):
                        payload["source_msg_id"] = f"{payload['source_msg_id']}:loop{loop_index}"
                    try:
                        await self.ingest_cb(payload)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.exception("回放事件失败，已停止当前样本")
                        return
                    self.emitted += 1
                if not self.loop or self._stop:
                    return
                loop_index += 1
        except asyncio.CancelledError:
            raise
        finally:
            self.running = False

    def _resolve(self, filename: str) -> Path:
        # 只允许样本目录里的文件名，避免路径穿越。
        if not filename or Path(filename).name != filename or not filename.endswith(".jsonl"):
            raise ValueError("样本文件名不合法")
        path = self.settings.samples_dir() / filename
        if not path.is_file():
            raise ValueError(f"找不到样本 {filename}")
        return path


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    text = path.read_text(encoding="utf-8")
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"{path.name}:{line_no} 不是 JSON 对象")
        row.setdefault("adapter", "sim")
        row["raw_ref"] = f"sim:{path.name}:{line_no}"
        rows.append(row)
    if not rows:
        raise ValueError(f"{path.name} 没有可回放的事件")
    return rows


async def _sleep_scaled(delay_ms: float, speed_of: Callable[[], int], stopped: Callable[[], bool]) -> None:
    if delay_ms <= 0:
        return
    remaining = delay_ms / 1000
    while remaining > 0:
        if stopped():
            return
        speed = speed_of() or 1
        # 小步睡眠，停止和变速不用等完整段结束。
        step = min(0.05, remaining / speed)
        await asyncio.sleep(step)
        remaining -= step * speed
