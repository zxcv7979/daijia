"""事件进入管线到写入 WS 队列的耗时。"""

from __future__ import annotations

import math
from collections import deque


class LatencyStats:
    def __init__(self, maxlen: int = 2000) -> None:
        self.received = 0
        self.published = 0
        self.duplicates = 0
        self.updates = 0
        self.dropped = 0
        self.rejected = 0
        self._samples_ms: deque[float] = deque(maxlen=maxlen)

    def observe(self, elapsed_ms: float) -> None:
        self._samples_ms.append(elapsed_ms)

    def snapshot(self) -> dict[str, float | int | None]:
        samples = sorted(self._samples_ms)
        return {
            "received": self.received,
            "published": self.published,
            "duplicates": self.duplicates,
            "updates": self.updates,
            "dropped": self.dropped,
            "rejected": self.rejected,
            "latency_ms": {
                "n": len(samples),
                "p50": _percentile(samples, 50),
                "p95": _percentile(samples, 95),
                "p99": _percentile(samples, 99),
                "max": samples[-1] if samples else None,
            },
        }


def _percentile(sorted_samples: list[float], percent: float) -> float | None:
    if not sorted_samples:
        return None
    if len(sorted_samples) == 1:
        return sorted_samples[0]
    rank = max(1, math.ceil(percent / 100 * len(sorted_samples)))
    return sorted_samples[rank - 1]
