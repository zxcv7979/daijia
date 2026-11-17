"""短浸泡入口。完整 8 小时用 scripts/soak_8h.py --duration 28800。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ops.soak import run_soak


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=30)
    parser.add_argument("--interval", type=float, default=0.5)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as folder:
        result = asyncio.run(run_soak(ROOT, Path(folder), duration_sec=args.duration, interval_sec=args.interval))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
