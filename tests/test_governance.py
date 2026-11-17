"""重连退避、event_id 去重窗口、队列满时丢最旧并告警。"""

from __future__ import annotations

import asyncio

from src.adapters.governance import IngressGovernor, ReconnectBackoff
from src.adapters.registry import AdapterRegistry
from src.settings import Settings


def _governor(maxsize: int = 4, window: float = 30) -> IngressGovernor:
    return IngressGovernor(
        queue_max=maxsize,
        dedup_window_sec=window,
        heartbeat_timeout_sec=3,
        backoff=ReconnectBackoff(),
    )


def test_backoff_stays_within_five_seconds_after_stable():
    backoff = ReconnectBackoff(base_sec=0.2, factor=2, cap_sec=5, stable_after_sec=2)
    for index in range(8):
        delay = backoff.next_delay(float(index))
        assert delay <= 5
    backoff.on_connected(100)
    backoff.note_stable(103)
    assert backoff.stable is True
    assert backoff.next_delay(103) <= 5
    assert backoff.next_delay(104) <= 5


def test_dedup_window_on_event_id():
    governor = _governor(window=30)
    assert governor.push("same", 10, {"n": 1}, 0) == "queued"
    assert governor.push("same", 12, {"n": 2}, 0) == "duplicate"
    assert governor.push("same", 50, {"n": 3}, 0) == "queued"
    assert governor.duplicates == 1
    assert governor.consistent()


def test_backpressure_drops_oldest_and_alerts():
    governor = _governor(maxsize=2)
    for index in range(5):
        assert governor.push(f"e{index}", float(index), {"n": index}, 0) == "queued"
    assert governor.dropped_oldest == 3
    assert governor.alert_count == 3
    assert governor.pending() == 2
    assert governor.consistent()
    assert governor.alerts[0]["policy"] == "drop_oldest"
    kept = [governor.pop().payload["n"] for _ in range(2)]
    assert kept == [3, 4]
    assert governor.consistent()


def test_heartbeat_timeout_marks_unhealthy_and_reconnects(project):
    registry = AdapterRegistry(Settings(project))

    async def go() -> None:
        started = await registry.start("mock", real_allowed=False)
        assert started["started"] is True
        registry.heartbeat("mock", 0)
        assert registry.check_liveness(1) is None
        missed = registry.check_liveness(10)
        assert missed is not None
        assert registry.health("mock")["state"] == "unhealthy"
        again = await registry.reconnect("mock", now=10, real_allowed=False)
        assert again["reconnected"] is True
        assert again["delay_sec"] <= 5
        assert registry.health("mock")["state"] == "healthy"

    asyncio.run(go())
