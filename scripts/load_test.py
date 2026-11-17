"""用模拟源压 1000 条/秒。不连接任何平台。

    python scripts/load_test.py
    python scripts/load_test.py --count 1000 --window 1
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from src.adapters.loadtest import run_mock_load


def main() -> None:
    parser = argparse.ArgumentParser(description="模拟源压测")
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--window", type=float, default=1.0)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    result = asyncio.run(run_mock_load(root, count=args.count, window_sec=args.window))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
