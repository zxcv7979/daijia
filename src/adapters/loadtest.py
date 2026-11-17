"""用模拟源把事件打进治理队列，再送到现有管道，测量入队到总线上的延迟。"""

from __future__ import annotations

import asyncio
import time
import tracemalloc
from pathlib import Path
from typing import Any

from src.bus.metrics import _percentile
from src.runtime import build_context


async def run_mock_load(root: Path, *, count: int = 1000, window_sec: float = 1.0) -> dict[str, Any]:
    if count < 1 or count > 20_000:
        raise ValueError("压测条数超出范围")
    if window_sec <= 0 or window_sec > 30:
        raise ValueError("压测窗口超出范围")
    ctx = build_context(root)
    governor = ctx.sources.governor
    tracemalloc.start()
    samples: list[float] = []
    producer_done = asyncio.Event()
    started = time.perf_counter()

    async def produce() -> None:
        interval = window_sec / count
        origin = time.perf_counter()
        for index in range(count):
            target = origin + index * interval
            delay = target - time.perf_counter()
            if delay > 0:
                await asyncio.sleep(delay)
            event_id = f"load-{index}"
            payload = {
                "adapter": "mock",
                "source_msg_id": event_id,
                "type": "like",
                "user_id": f"load-user-{index}",
                "nickname": f"压{index}",
                "raw_ref": f"mock:load:{index}",
            }
            governor.push(event_id, time.time(), payload, time.perf_counter())
        producer_done.set()

    async def consume() -> None:
        while not (producer_done.is_set() and governor.pending() == 0):
            item = governor.pop()
            if item is None:
                await asyncio.sleep(0)
                continue
            await ctx.ingest(item.payload)
            samples.append((time.perf_counter() - item.enqueued_at) * 1000)

    try:
        await asyncio.gather(produce(), consume())
        elapsed = time.perf_counter() - started
        _current, peak = tracemalloc.get_traced_memory()
        ordered = sorted(samples)
        gov = governor.snapshot()
        pipeline = ctx.stats.snapshot()
        return {
            "count": count,
            "window_sec": window_sec,
            "elapsed_sec": round(elapsed, 3),
            "offered_rate_per_sec": round(count / elapsed, 1) if elapsed else None,
            "e2e_ms": {
                "n": len(ordered),
                "p50": _percentile(ordered, 50),
                "p95": _percentile(ordered, 95),
                "p99": _percentile(ordered, 99),
                "max": ordered[-1] if ordered else None,
            },
            "pipeline_ms": pipeline["latency_ms"],
            "memory_peak_bytes": peak,
            "governor": gov,
            "published": pipeline["published"],
            "dropped_pipeline": pipeline["dropped"],
        }
    finally:
        tracemalloc.stop()
        ctx.close()
