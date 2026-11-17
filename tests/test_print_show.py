"""虚拟打印进度和里程碑。不依赖真实打印机。"""

from __future__ import annotations

from src.bus.event_bus import EventBus
from src.clock import FakeClock
from src.emotion.engine import EmotionEngine
from src.mapping.table import MappingTable
from src.models import AvatarType, PrintStyle
from src.print_show.jobs import PrintShow
from src.settings import Settings
from src.store import Store


def test_progress_marks_and_status(project, tmp_path):
    settings = Settings(project)
    clock = FakeClock()
    bus = EventBus(clock=clock)
    engine = EmotionEngine(settings, bus, MappingTable(settings), clock)
    store = Store(tmp_path / "print.db")
    try:
        printer = PrintShow(settings, bus, store, engine, clock)
        job = printer.create(style=PrintStyle.cartoon, avatar_type=AvatarType.stylized, duration_sec=10)
        assert job.status.value == "queued"
        assert job.duration_sec == 10
        clock.advance(2.5)
        printer.tick()
        assert job.progress == 25
        assert job.status.value == "printing"
        assert printer._emitted[job.job_id] == {25}
        clock.advance(5)  # 7.5s → 75%，仍在层层生长
        printer.tick()
        assert job.status.value == "printing"
        assert 50 in printer._emitted[job.job_id]
        assert 75 in printer._emitted[job.job_id]
        clock.advance(2.5)
        printer.tick()
        assert job.status.value == "done"
        assert job.progress == 100
        assert printer._emitted[job.job_id] == {25, 50, 75, 90, 100}
        kinds = [item["kind"] for item in bus.buffered_messages()]
        assert "print_job" in kinds
        assert "print_progress" in kinds
        assert "fx_cue" in kinds
    finally:
        store.close()
