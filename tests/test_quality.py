"""画面降档、粒子上限和同时在场特效数量。"""

from __future__ import annotations

from src.mapping.table import MappingTable
from src.models import EventType, LiveEvent
from src.overlay.quality import QualityState, admit_fx, particle_budget, skip_secondary, step_quality
from src.settings import Settings


def test_downshift_after_budget_and_recovers():
    state = QualityState()
    for _ in range(7):
        step_quality(state, 13)
        assert state.level == 0
    step_quality(state, 13)
    assert state.level == 1
    assert state.downshifted is True
    for _ in range(8):
        step_quality(state, 18)
    assert state.level == 2
    for _ in range(44):
        step_quality(state, 8)
        assert state.level == 2
    step_quality(state, 8)
    assert state.level == 1
    assert skip_secondary(1, True) is True
    assert skip_secondary(0, True) is False


def test_particle_and_fx_caps():
    assert particle_budget(0, 100) == 100
    assert particle_budget(1, 100) == 50
    assert particle_budget(2, 100) == 25
    assert particle_budget(0, 50_000) == 20_000
    assert admit_fx(7, 8) is True
    assert admit_fx(8, 8) is False


def test_keyword_and_price_conditions(project):
    table = MappingTable(Settings(project))

    def event(**kwargs: object) -> LiveEvent:
        data = dict(
            event_id="k1",
            type=EventType.danmaku,
            user_id_hash="h",
            nickname_masked="甲*",
            text="大家好",
            price=0,
            combo_count=1,
            ts=1,
        )
        data.update(kwargs)
        return LiveEvent.model_validate(data)

    plain = table.resolve(event())
    hinted = table.resolve(event(text="榜一来了"))
    cheap = table.resolve(event(event_id="g", type=EventType.gift, price=5, text=None, gift_id="local_rose", gift_name="小花"))
    combo = table.resolve(event(event_id="c", type=EventType.gift, price=5, combo_count=6, text=None, gift_id="local_rose", gift_name="小花"))
    assert plain is not None and plain.level == "L1" and plain.fx == "danmaku_float" and plain.atmosphere_only
    assert hinted is not None and hinted.level == "L1" and hinted.fx == "danmaku_rank_hint" and hinted.atmosphere_only
    assert cheap is not None and cheap.level == "L2" and cheap.particles == 48
    assert combo is not None and combo.level == "L2" and combo.secondary is True


def test_overlay_config_follows_hot_reload(client):
    body = client.get("/api/overlay/config").json()
    assert body["width"] == 1920
    assert body["height"] == 1080
    assert body["max_fx"] == 8
    assert body["max_particles"] == 20000
    assert body["frame_budget_ms"] == 12
    assert body["transparent"] is True
    current = client.get("/api/mappings").json()["yaml"]
    updated = current.replace("particles: 8", "particles: 12", 1)
    saved = client.put("/api/mappings", json={"yaml": updated})
    assert saved.status_code == 200
    again = client.get("/api/overlay/config").json()
    assert again["performances"]["sparkle_ambient"]["particles"] == 12


def test_on_screen_fx_cap(project):
    from src.bus.event_bus import EventBus
    from src.clock import FakeClock
    from src.emotion.engine import EmotionEngine

    settings = Settings(project)
    settings.default_model.emotion.max_on_screen = 8
    for key in settings.default_model.emotion.cooldowns_ms:
        settings.default_model.emotion.cooldowns_ms[key] = 0
    clock = FakeClock()
    engine = EmotionEngine(settings, EventBus(clock=clock), MappingTable(settings), clock)
    for index in range(12):
        clock.advance(0.01)
        engine.handle(
            LiveEvent(
                event_id=f"cap-{index}",
                type=EventType.enter,
                user_id_hash=f"h{index}",
                nickname_masked="甲*",
                ts=clock.time(),
            )
        )
    assert len(engine.snapshot()["active"]) <= 8
