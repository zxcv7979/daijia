"""虚拟打印任务。服务器按时间推进进度，并在 25/50/75/90/100 喂给情绪引擎。"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from src.bus.event_bus import EventBus
from src.clock import SystemClock
from src.mapping.table import Resolution
from src.models import AvatarType, LiveEvent, PrintJob, PrintStatus, PrintStyle, dump_model
from src.settings import Settings
from src.store import Store

if TYPE_CHECKING:
    from src.emotion.engine import EmotionEngine


_STATUS_STEPS = (
    (70, PrintStatus.printing),
    (90, PrintStatus.refining),
    (100, PrintStatus.revealing),
)


class PrintShow:
    def __init__(
        self,
        settings: Settings,
        bus: EventBus,
        store: Store,
        emotion: EmotionEngine,
        clock: SystemClock,
    ) -> None:
        self.settings = settings
        self.bus = bus
        self.store = store
        self.emotion = emotion
        self.clock = clock
        self.jobs: dict[str, PrintJob] = {}
        self._started_mono: dict[str, float] = {}
        self._emitted: dict[str, set[int]] = {}
        self._last_saved_progress: dict[str, float] = {}

    def create(
        self,
        *,
        style: PrintStyle,
        avatar_type: AvatarType,
        duration_sec: float | None = None,
        source_event_id: str | None = None,
        avatar_id: str | None = None,
    ) -> PrintJob:
        duration = duration_sec if duration_sec is not None else self.settings.default_model.print_show.default_duration_sec
        if duration <= 0 or duration > 600:
            raise ValueError("打印时长需要在 0 到 600 秒之间")
        job_id = uuid.uuid4().hex
        job = PrintJob(
            job_id=job_id,
            avatar_id=avatar_id or f"av-{job_id[:8]}",
            avatar_type=avatar_type,
            source_event_id=source_event_id,
            style=style,
            status=PrintStatus.queued,
            progress=0,
            duration_sec=duration,
            timeline_ref=f"virtual:{job_id}",
            created_at=self.clock.time(),
        )
        self.jobs[job_id] = job
        self._started_mono[job_id] = self.clock.monotonic()
        self._emitted[job_id] = set()
        self._persist(job, force=True)
        self.bus.publish("print_job", dump_model(job))
        return job

    def maybe_autoprint(self, event: LiveEvent, resolution: Resolution | None) -> PrintJob | None:
        if resolution is None or not resolution.fired or resolution.print_style is None or resolution.print_avatar is None:
            return None
        if any(job.source_event_id == event.event_id for job in self.jobs.values()):
            return None
        return self.create(
            style=resolution.print_style,
            avatar_type=resolution.print_avatar,
            source_event_id=event.event_id,
            avatar_id=f"av-{event.user_id_hash[:8]}",
        )

    def tick(self) -> None:
        now = self.clock.monotonic()
        cues = self.settings.default_model.print_show.progress_cues
        for job_id, job in list(self.jobs.items()):
            if job.status in (PrintStatus.done, PrintStatus.failed):
                continue
            elapsed = now - self._started_mono[job_id]
            progress = min(100.0, (elapsed / job.duration_sec) * 100)
            previous_status = job.status
            job.progress = round(progress, 2)
            job.status = _status_for(progress)
            status_changed = job.status != previous_status
            self._persist(job, force=status_changed or progress >= 100)
            if status_changed or _progress_step_changed(self._last_saved_progress.get(job_id, -1), progress):
                self.bus.publish(
                    "print_progress",
                    {"job_id": job.job_id, "progress": job.progress, "status": job.status.value},
                )
            for mark in cues:
                if progress + 1e-6 >= mark and mark not in self._emitted[job_id]:
                    self._emitted[job_id].add(mark)
                    self.emotion.on_print_progress(mark, job.job_id)
            if progress >= 100:
                job.status = PrintStatus.done
                job.progress = 100
                self._persist(job, force=True)
                self.bus.publish(
                    "print_progress",
                    {"job_id": job.job_id, "progress": 100, "status": job.status.value},
                )

    def public_jobs(self) -> list[dict]:
        return [dump_model(job) for job in sorted(self.jobs.values(), key=lambda item: item.created_at, reverse=True)]

    def public_job(self, job_id: str) -> dict | None:
        job = self.jobs.get(job_id)
        if job is None:
            return None
        return dump_model(job)

    def _persist(self, job: PrintJob, *, force: bool) -> None:
        previous = self._last_saved_progress.get(job.job_id, -1)
        if force or abs(job.progress - previous) >= 1:
            payload = dump_model(job)
            self.store.save_job(payload)
            self._last_saved_progress[job.job_id] = job.progress


def _status_for(progress: float) -> PrintStatus:
    if progress <= 0:
        return PrintStatus.queued
    if progress < 70:
        return PrintStatus.printing
    if progress < 90:
        return PrintStatus.refining
    if progress < 100:
        return PrintStatus.revealing
    return PrintStatus.done


def _progress_step_changed(previous: float, current: float) -> bool:
    if previous < 0:
        return True
    return int(previous) != int(current)
