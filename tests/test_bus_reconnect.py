"""30 秒重连缓冲。过期消息被丢掉，未过期的按 seq 补发。"""

from __future__ import annotations

from src.bus.event_bus import EventBus
from src.clock import FakeClock


def test_buffer_keeps_30s_and_replays_cursor():
    clock = FakeClock()
    bus = EventBus(clock=clock)
    first = bus.publish("event", {"event": {"event_id": "old"}})
    clock.advance(10)
    middle = bus.publish("emotion", {"emotion": "joy"})
    clock.advance(10)
    newest = bus.publish("fx_cue", {"fx": "sparkle_ambient"})
    missed, gap = bus.replay_since(first["seq"])
    assert gap is False
    assert [item["seq"] for item in missed] == [middle["seq"], newest["seq"]]
    clock.advance(21)
    # 前两条已经超过 30 秒，从旧游标补发时要标明中间有空洞。
    remaining, gap = bus.replay_since(first["seq"])
    assert [item["seq"] for item in remaining] == [newest["seq"]]
    assert gap is True
    fresh, fresh_gap = bus.replay_since(0)
    assert [item["seq"] for item in fresh] == [newest["seq"]]
    assert fresh_gap is False
    clock.advance(10)
    assert bus.replay_since(0)[0] == []


def test_exactly_30_seconds_still_retained():
    clock = FakeClock()
    bus = EventBus(clock=clock)
    bus.publish("fx_cue", {"fx": "sparkle_ambient", "level": "L0"})
    clock.advance(30)
    assert len(bus.replay_since(0)[0]) == 1
    clock.advance(0.01)
    assert bus.replay_since(0)[0] == []


def test_messages_are_versioned_and_addressable():
    bus = EventBus(clock=FakeClock())
    kinds = ["event", "emotion", "fx_cue", "print_job", "print_progress"]
    messages = [bus.publish(kind, {"n": index}) for index, kind in enumerate(kinds)]
    assert [item["seq"] for item in messages] == [1, 2, 3, 4, 5]
    assert all(item["v"] == 1 for item in messages)
