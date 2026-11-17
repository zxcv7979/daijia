"""情绪上升、衰减、优先级压低，以及弹幕不抢礼物主秀。"""

from __future__ import annotations

import pytest

from src.bus.event_bus import EventBus
from src.clock import FakeClock
from src.emotion.engine import EmotionEngine, intensity_at
from src.mapping.table import MappingTable
from src.models import EventType, LiveEvent
from src.settings import Settings


def _engine(project, clock: FakeClock | None = None):
    settings = Settings(project)
    clock = clock or FakeClock()
    bus = EventBus(clock=clock)
    engine = EmotionEngine(settings, bus, MappingTable(settings), clock)
    return engine, bus, settings, clock


def _event(**overrides) -> LiveEvent:
    data = dict(
        event_id="e1",
        type=EventType.danmaku,
        user_id_hash="hash",
        nickname_masked="甲*",
        price=0,
        ts=1.0,
        text="你好",
        combo_count=1,
    )
    data.update(overrides)
    return LiveEvent.model_validate(data)


def test_intensity_curve_matches_sample(project):
    engine, _bus, settings, clock = _engine(project)
    engine.trigger_level("L4")
    target = settings.mappings_model.tiers["L4"].intensity
    rise = settings.default_model.emotion.rise_ms
    hold = settings.mappings_model.tiers["L4"].hold_ms or 0
    half = settings.default_model.emotion.decay_half_life_s
    assert engine.snapshot()["intensity"] == pytest.approx(0.0, abs=1e-6)
    assert engine.snapshot()["phase"] == "rise"
    clock.advance(rise / 1000)
    snap = engine.snapshot()
    assert snap["phase"] == "hold"
    assert snap["intensity"] == pytest.approx(target, abs=1e-6)
    assert snap["emotion"] == "awe"
    clock.advance(hold / 1000 + half)
    decayed = engine.snapshot()
    assert decayed["phase"] == "decay"
    expected = intensity_at(rise + hold + half * 1000, target, rise, hold, half)
    assert decayed["intensity"] == pytest.approx(expected, rel=1e-6)
    assert decayed["decay_half_life"] == half


def test_higher_priority_ducks_lower(project):
    engine, _bus, _settings, _clock = _engine(project)
    engine.handle(_event(event_id="like", type=EventType.like, text=None))
    engine.handle(
        _event(event_id="big", type=EventType.gift, price=200, gift_id="local_ship", gift_name="星舰", text=None)
    )
    snap = engine.snapshot()
    assert snap["emotion"] == "awe"
    assert snap["priority"] == 8
    assert snap["is_ducking"] is True
    assert any(item["level"] == "L0" and item["ducked"] for item in snap["active"])


def test_manual_preview_does_not_block_the_next_gift(project):
    engine, _bus, _settings, clock = _engine(project)
    engine.trigger_level("L4")
    clock.advance(0.2)
    fired = engine.handle(
        _event(event_id="rank", type=EventType.gift, price=520, gift_id="local_flagship", gift_name="榜一星舰", text=None),
        highlight="rank1",
    )
    assert fired is not None and fired.fired is True
    assert fired.fx == "bangyi_rank1"
    snap = engine.snapshot()
    assert snap["emotion"] == "awe"
    assert snap["priority"] == 8


def test_manual_trigger_replaces_current_show(project):
    engine, _bus, _settings, _clock = _engine(project)
    engine.trigger_level("L4")
    engine.trigger_level("L0")
    snap = engine.snapshot()
    assert snap["emotion"] == "ambient"
    assert snap["priority"] == 0
    assert [item["level"] for item in snap["active"]] == ["L0"]


def test_danmaku_does_not_steal_gift_show(project):
    engine, bus, _settings, clock = _engine(project)
    engine.trigger_level("L4")
    clock.advance(0.3)
    before = engine.snapshot()
    result = engine.handle(_event(event_id="dm", text="榜一榜一"))
    after = engine.snapshot()
    assert result is not None and result.fired is True
    assert result.atmosphere_only is True
    assert after["emotion"] == "awe"
    assert after["priority"] == before["priority"] == 8
    assert after["source_event"] == before["source_event"]
    fx = [msg for msg in bus.buffered_messages() if msg["kind"] == "fx_cue"]
    assert any(item["data"]["level"] == "L1" for item in fx)
    assert any(item["data"]["level"] == "L4" for item in fx)


def test_cooldown_blocks_second_gift_fx(project):
    engine, bus, _settings, clock = _engine(project)
    first = engine.handle(
        _event(event_id="g1", type=EventType.gift, price=1, gift_id="local_rose", gift_name="小花")
    )
    clock.advance(0.1)
    second = engine.handle(
        _event(event_id="g2", type=EventType.gift, price=1, gift_id="local_rose", gift_name="小花")
    )
    assert first is not None and first.fired is True and first.level == "L2"
    assert second is not None and second.fired is False
    fx = [msg for msg in bus.buffered_messages() if msg["kind"] == "fx_cue" and msg["data"]["level"] == "L2"]
    assert len(fx) == 1


def test_max_on_screen_keeps_stronger_cue(project):
    engine, _bus, settings, _clock = _engine(project)
    settings.default_model.emotion.max_on_screen = 1
    engine.trigger_level("L4")
    added = engine.handle(_event(event_id="dm"))
    snap = engine.snapshot()
    assert added is not None and added.fired is False
    assert [item["level"] for item in snap["active"]] == ["L4"]
    blocked = engine.handle(_event(event_id="like", type=EventType.like, text=None))
    # 观众侧的低优先级事件在满员时不能挤掉 L4。手动挡位则另计，见 test_manual_trigger_replaces_current_show。
    assert blocked is not None and blocked.fired is False
    assert [item["level"] for item in engine.snapshot()["active"]] == ["L4"]


def test_print_cue_feeds_emotion_without_overriding_rank1(project):
    engine, _bus, _settings, _clock = _engine(project)
    engine.on_print_progress(50, "job-1")
    alone = engine.snapshot()
    assert alone["emotion"] == "hype"
    assert alone["priority"] == 6
    engine.trigger_level("L4")
    engine.on_print_progress(100, "job-1")
    topped = engine.snapshot()
    assert topped["emotion"] == "awe"
    assert topped["priority"] == 8
    assert any(item["level"] == "P100" and item["ducked"] for item in topped["active"])


def test_price_bands_and_rank1_fx(project):
    table = MappingTable(Settings(project))

    def gift(price: float, highlight: str | None = None, event_id: str = "g"):
        return table.resolve(
            _event(
                event_id=event_id,
                type=EventType.gift,
                price=price,
                gift_id="local_x",
                gift_name="礼物",
            ),
            highlight=highlight,
        )

    cheap = gift(1)
    mid = gift(30)
    big = gift(188)
    rank = gift(520, highlight="rank1")
    assert cheap is not None and cheap.level == "L2" and cheap.print_style is None
    assert mid is not None and mid.level == "L3" and mid.print_style.value == "cartoon"
    assert big is not None and big.level == "L4" and big.fx == "print_hologram"
    assert big.print_style is not None and big.print_style.value == "hologram"
    assert rank is not None and rank.fx == "bangyi_rank1" and rank.level == "L4"
    danmaku = table.resolve(_event())
    assert danmaku is not None and danmaku.level == "L1" and danmaku.atmosphere_only is True
    follow = table.resolve(_event(type=EventType.follow, event_id="f"))
    assert follow is not None and follow.level == "L2"
