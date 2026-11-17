"""进程内存、文件句柄，以及能读到的 GPU 利用率。"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


def sample_metrics() -> dict[str, Any]:
    return {
        "rss_kb": _rss_kb(),
        "fds": _fd_count(),
        "gpu": _gpu(),
    }


def _rss_kb() -> int | None:
    status = Path("/proc/self/status")
    if not status.is_file():
        return None
    for line in status.read_text(encoding="utf-8").splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1])
    return None


def _fd_count() -> int | None:
    folder = Path("/proc/self/fd")
    if not folder.is_dir():
        return None
    return len(list(folder.iterdir()))


def _gpu() -> dict[str, float] | None:
    if shutil.which("nvidia-smi") is None:
        return None
    try:
        completed = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    first = completed.stdout.strip().splitlines()[0]
    util, memory = [part.strip() for part in first.split(",")]
    return {"util": float(util) / 100, "memory_mib": float(memory)}


def growth(samples: list[dict[str, Any]]) -> dict[str, int | None]:
    if not samples:
        return {"rss_kb": None, "fds": None}
    return {
        "rss_kb": _delta(samples, "rss_kb"),
        "fds": _delta(samples, "fds"),
    }


def _delta(samples: list[dict[str, Any]], key: str) -> int | None:
    start = samples[0].get(key)
    end = samples[-1].get(key)
    if start is None or end is None:
        return None
    return int(end) - int(start)


def growth_ratio(samples: list[dict[str, Any]], key: str = "rss_kb") -> float | None:
    if len(samples) < 2:
        return None
    start = samples[0].get(key)
    end = samples[-1].get(key)
    if start in (None, 0) or end is None:
        return None
    return (float(end) - float(start)) / float(start)


def budget_breaches(samples: list[dict[str, Any]], *, rss_kb: int, fds: int) -> list[str]:
    delta = growth(samples)
    found = []
    if delta["rss_kb"] is not None and delta["rss_kb"] > rss_kb:
        found.append("rss")
    if delta["fds"] is not None and delta["fds"] > fds:
        found.append("fds")
    return found
