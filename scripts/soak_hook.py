"""P6 浸泡测试的挂钩。现在只转去跑 P5 的短队列检查，不开始长时间浸泡。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.print_queue_bench import run


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", type=int, default=20)
    args = parser.parse_args()
    result = run(args.jobs)
    print("P6 浸泡未实现。已改跑虚拟打印队列检查。")
    print(
        f"jobs={result['jobs']} done={result['done']} rebuilds={result['rebuilds']} "
        f"growth={result['growth_bytes']} peak={result['peak_bytes']} ok={result['ok']}"
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
