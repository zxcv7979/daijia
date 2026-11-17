"""可替换时钟。测试用 FakeClock 推动情绪衰减和 30 秒缓冲过期。"""

from __future__ import annotations

import time


class SystemClock:
    def time(self) -> float:
        return time.time()

    def monotonic(self) -> float:
        return time.monotonic()


class FakeClock:
    """墙钟与单调钟一起前进，方便断言衰减和缓冲。"""

    def __init__(self, wall: float = 1_700_000_000.0) -> None:
        self._wall = wall
        self._mono = 0.0

    def time(self) -> float:
        return self._wall

    def monotonic(self) -> float:
        return self._mono

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("不能把时钟往回拨")
        self._wall += seconds
        self._mono += seconds
