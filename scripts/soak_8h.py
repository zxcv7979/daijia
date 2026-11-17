"""8 小时浸泡。云上机器跑短时长，完整 8 小时留给实机。

    python scripts/soak_8h.py --duration 600
    python scripts/soak_8h.py --duration 28800 --interval 2
"""

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
    parser = argparse.ArgumentParser(description="虚拟演出浸泡")
    parser.add_argument("--duration", type=float, default=8 * 3600)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as folder:
        result = asyncio.run(
            run_soak(ROOT, Path(folder), duration_sec=args.duration, interval_sec=args.interval)
        )
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
