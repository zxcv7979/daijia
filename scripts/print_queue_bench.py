"""连续虚拟打印的无头检查。不启动浏览器，也不连打印机。

实机 60fps 和画面泄漏要在 OBS 里看，这里只确认队列能走完、uniforms 不要求重建网格、内存增量有上限。
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bus.event_bus import EventBus
from src.clock import FakeClock
from src.emotion.engine import EmotionEngine
from src.mapping.table import MappingTable
from src.models import AvatarType, PrintStatus, PrintStyle
from src.print_show.jobs import PrintShow
from src.settings import Settings
from src.store import Store


def run(jobs: int) -> dict[str, float | int | bool]:
    settings = Settings(ROOT)
    clock = FakeClock()
    bus = EventBus(clock=clock)
    engine = EmotionEngine(settings, bus, MappingTable(settings), clock)
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "bench.db")
        printer = PrintShow(settings, bus, store, engine, clock)
        tracemalloc.start()
        before, _ = tracemalloc.get_traced_memory()
        for _ in range(jobs):
            printer.create(style=PrintStyle.cartoon, avatar_type=AvatarType.stylized, duration_sec=0.05)
        for _ in range(jobs * 4):
            if not printer.queue_ids():
                break
            printer.tick()
            clock.advance(0.05)
        after, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        done = sum(1 for job in printer.jobs.values() if job.status == PrintStatus.done)
        rebuilds = sum(
            1
            for item in bus.buffered_messages()
            if item["kind"] in {"print_progress", "print_job"} and item["data"].get("rebuild_geometry") is True
        )
        store.close()
    return {
        "jobs": jobs,
        "done": done,
        "rebuilds": rebuilds,
        "growth_bytes": after - before,
        "peak_bytes": peak,
        "ok": done == jobs and rebuilds == 0 and after - before < 2_000_000,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", type=int, default=20)
    args = parser.parse_args()
    result = run(args.jobs)
    print(
        f"jobs={result['jobs']} done={result['done']} rebuilds={result['rebuilds']} "
        f"growth={result['growth_bytes']} peak={result['peak_bytes']} ok={result['ok']}"
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
