"""连接治理：心跳、退避、按 event_id 去重、队列满时丢最旧。

丢弃策略是 drop oldest（丢掉队列里最旧的一条，接纳新事件）。
直播演出要的是现在的观众，而不是堵住队列后一直播过期事件。
每次因此丢弃都会增加 dropped_oldest，并记一条 backpressure 告警。
除此之外的丢失视为违规：offered 必须等于 duplicates + enqueued。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class QueuedEvent:
    event_id: str
    ts: float
    payload: dict[str, Any]
    enqueued_at: float


@dataclass
class ReconnectBackoff:
    """指数退避，上限 5 秒。连接稳定之后，下一次重连等待也不超过 5 秒。"""

    base_sec: float = 0.2
    factor: float = 2.0
    cap_sec: float = 5.0
    stable_after_sec: float = 2.0
    attempt: int = 0
    stable: bool = False
    connected_at: float | None = None

    def __post_init__(self) -> None:
        if self.cap_sec > 5:
            raise ValueError("重连等待上限不能超过 5 秒")

    def on_connected(self, now: float) -> None:
        self.connected_at = now

    def note_stable(self, now: float) -> None:
        if self.connected_at is None:
            return
        if now - self.connected_at >= self.stable_after_sec:
            self.stable = True
            self.attempt = 0

    def next_delay(self, now: float) -> float:
        if self.stable:
            self.stable = False
            self.connected_at = None
            self.attempt = 0
            return min(self.base_sec, self.cap_sec)
        delay = min(self.cap_sec, self.base_sec * (self.factor ** self.attempt))
        self.attempt += 1
        self.connected_at = None
        return delay


@dataclass
class IngressGovernor:
    queue_max: int
    dedup_window_sec: float
    heartbeat_timeout_sec: float
    backoff: ReconnectBackoff
    offered: int = 0
    duplicates: int = 0
    enqueued: int = 0
    delivered: int = 0
    dropped_oldest: int = 0
    alert_count: int = 0
    alerts: list[dict[str, Any]] = field(default_factory=list)
    last_reconnect_delay: float | None = None
    _items: deque[QueuedEvent] = field(default_factory=deque)
    _seen: dict[str, float] = field(default_factory=dict)

    def push(self, event_id: str, ts: float, payload: dict[str, Any], enqueued_at: float) -> str:
        self.offered += 1
        self._expire(ts)
        previous = self._seen.get(event_id)
        if previous is not None and ts - previous <= self.dedup_window_sec:
            self.duplicates += 1
            return "duplicate"
        self._seen[event_id] = ts
        if len(self._items) >= self.queue_max:
            self._items.popleft()
            self.dropped_oldest += 1
            self.alert_count += 1
            if len(self.alerts) < 50:
                self.alerts.append(
                    {
                        "type": "backpressure",
                        "policy": "drop_oldest",
                        "dropped_oldest": self.dropped_oldest,
                        "queue_max": self.queue_max,
                    }
                )
        self._items.append(QueuedEvent(event_id, ts, payload, enqueued_at))
        self.enqueued += 1
        return "queued"

    def pop(self) -> QueuedEvent | None:
        if not self._items:
            return None
        self.delivered += 1
        return self._items.popleft()

    def pending(self) -> int:
        return len(self._items)

    def consistent(self) -> bool:
        """没有策略之外的丢失。"""

        return self.offered == self.duplicates + self.enqueued and self.enqueued == (
            self.delivered + self.pending() + self.dropped_oldest
        )

    def snapshot(self) -> dict[str, object]:
        return {
            "offered": self.offered,
            "duplicates": self.duplicates,
            "enqueued": self.enqueued,
            "delivered": self.delivered,
            "pending": self.pending(),
            "dropped_oldest": self.dropped_oldest,
            "dropped_silent": 0 if self.consistent() else self.offered,
            "alert_count": self.alert_count,
            "alerts": list(self.alerts),
            "policy": "drop_oldest",
            "last_reconnect_delay_sec": self.last_reconnect_delay,
            "consistent": self.consistent(),
        }

    def _expire(self, ts: float) -> None:
        if len(self._seen) < 4000:
            return
        cutoff = ts - self.dedup_window_sec
        self._seen = {key: seen for key, seen in self._seen.items() if seen >= cutoff}
