"""时间轴阶段、插队、失败补偿，以及每帧不重建网格。"""

from __future__ import annotations

from src.bus.event_bus import EventBus
from src.clock import FakeClock
from src.emotion.engine import EmotionEngine
from src.mapping.table import MappingTable
from src.models import AvatarType, PrintStyle
from src.print_show.jobs import PrintShow
from src.print_show.timeline import clip_y, phase_of, print_uniforms
from src.settings import Settings
from src.store import Store


def test_phases_and_clip_do_not_rebuild_geometry():
    assert phase_of(0) == "preheat"
    assert phase_of(4) == "preheat"
    assert phase_of(5) == "layer"
    assert phase_of(84) == "layer"
    assert phase_of(85) == "refine"
    assert phase_of(94) == "refine"
    assert phase_of(95) == "reveal"
    assert phase_of(100) == "done"
    previous = -1.0
    for progress in range(5, 85):
        current = clip_y(progress)
        assert current >= previous
        previous = current
    view = print_uniforms(50, grain=0.4)
    assert view["rebuild_geometry"] is False
    assert view["hud"] == "层层生长"
    assert print_uniforms(2)["hud"] == "任务已接收"
    assert print_uniforms(90)["hold_breath"] == 1.0
    assert print_uniforms(100)["burst"] == 1.0
    assert print_uniforms(1, compensation=True)["hud"] == "补偿重打"


def test_hologram_waits_behind_the_job_on_the_bed(project, tmp_path):
    printer = _printer(project, tmp_path)
    try:
        first = printer.create(style=PrintStyle.cartoon, avatar_type=AvatarType.stylized, duration_sec=10)
        second = printer.create(style=PrintStyle.realistic, avatar_type=AvatarType.stylized, duration_sec=10)
        jumped = printer.create(style=PrintStyle.hologram, avatar_type=AvatarType.stylized, duration_sec=10)
        assert printer.queue_ids() == [first.job_id, jumped.job_id, second.job_id]
        assert jumped.progress == 0
        printer.clock.advance(10)
        printer.tick()
        assert first.status.value == "done"
        assert printer.queue_ids()[0] == jumped.job_id
    finally:
        printer.store.close()


def test_failure_replays_then_continues(project, tmp_path):
    printer = _printer(project, tmp_path)
    try:
        first = printer.create(style=PrintStyle.cartoon, avatar_type=AvatarType.stylized, duration_sec=10)
        nxt = printer.create(style=PrintStyle.realistic, avatar_type=AvatarType.stylized, duration_sec=10)
        replay = printer.fail_active()
        assert first.status.value == "failed"
        assert replay is not None
        assert replay.timeline_ref.startswith("compensate:")
        assert printer.queue_ids() == [replay.job_id, nxt.job_id]
        printer.tick()
        printer.clock.advance(10)
        printer.tick()
        assert replay.status.value == "done"
        assert printer.queue_ids() == [nxt.job_id]
    finally:
        printer.store.close()


def test_cue_beats_reach_emotion(project, tmp_path):
    printer = _printer(project, tmp_path)
    try:
        printer.create(style=PrintStyle.cartoon, avatar_type=AvatarType.stylized, duration_sec=10)
        printer.clock.advance(9)
        printer.tick()
        beats = [item["data"].get("beat") for item in printer.bus.buffered_messages() if item["kind"] == "fx_cue"]
        assert "hold_breath" in beats
        printer.clock.advance(1)
        printer.tick()
        beats = [item["data"].get("beat") for item in printer.bus.buffered_messages() if item["kind"] == "fx_cue"]
        assert "burst" in beats
    finally:
        printer.store.close()


def _printer(project, tmp_path) -> PrintShow:
    settings = Settings(project)
    clock = FakeClock()
    bus = EventBus(clock=clock)
    engine = EmotionEngine(settings, bus, MappingTable(settings), clock)
    store = Store(tmp_path / "print.db")
    show = PrintShow(settings, bus, store, engine, clock)
    show.clock = clock
    return show
