"""虚拟打印任务。服务器按时间推进进度，并在 25/50/75/90/100 喂给情绪引擎。"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from src.bus.event_bus import EventBus
from src.clock import SystemClock
from src.mapping.table import Resolution
from src.models import AvatarType, LiveEvent, PrintJob, PrintStatus, PrintStyle, dump_model
from src.print_show.timeline import can_jump_queue, print_uniforms
from src.settings import Settings
from src.store import Store

if TYPE_CHECKING:
    from src.emotion.engine import EmotionEngine


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
        self.order: list[str] = []
        self._started_mono: dict[str, float] = {}
        self._emitted: dict[str, set[int]] = {}
        self._last_saved_progress: dict[str, float] = {}
        self._compensation: set[str] = set()

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
        job = self._make(style, avatar_type, duration, source_event_id, avatar_id, compensation=False)
        self._place(job)
        if self._active_id() == job.job_id:
            self._started_mono[job.job_id] = self.clock.monotonic()
        self._persist(job, force=True)
        self.bus.publish("print_job", self._public_progress(job))
        return job

    def maybe_autoprint(self, event: LiveEvent, resolution: Resolution | None) -> PrintJob | None:
        if resolution is None or not resolution.fired or resolution.print_style is None or resolution.print_avatar is None:
            return None
        if any(job.source_event_id == event.event_id for job in self.jobs.values()):
            return None
        cfg = self.settings.default_model.print_show
        duration = cfg.show_max_sec if resolution.print_style == PrintStyle.hologram else cfg.default_duration_sec
        return self.create(
            style=resolution.print_style,
            avatar_type=resolution.print_avatar,
            duration_sec=duration,
            source_event_id=event.event_id,
            avatar_id=f"av-{event.user_id_hash[:8]}",
        )

    def fail_active(self) -> PrintJob | None:
        """当前任务失败后插一条补偿重打，再继续后面的队列。"""

        active_id = self._active_id()
        if active_id is None:
            return None
        job = self.jobs[active_id]
        job.status = PrintStatus.failed
        self._persist(job, force=True)
        self.bus.publish("print_progress", self._public_progress(job))
        replay = self._make(job.style, job.avatar_type, job.duration_sec, job.source_event_id, job.avatar_id, compensation=True)
        replay.timeline_ref = f"compensate:{job.job_id}"
        self._compensation.add(replay.job_id)
        index = self.order.index(active_id) + 1
        self.order.insert(index, replay.job_id)
        self._started_mono.pop(active_id, None)
        self._persist(replay, force=True)
        self.bus.publish("print_job", self._public_progress(replay))
        return replay

    def tick(self) -> None:
        active_id = self._active_id()
        if active_id is None:
            return
        job = self.jobs[active_id]
        if active_id not in self._started_mono:
            self._started_mono[active_id] = self.clock.monotonic()
        now = self.clock.monotonic()
        cues = self.settings.default_model.print_show.progress_cues
        elapsed = now - self._started_mono[active_id]
        progress = min(100.0, (elapsed / job.duration_sec) * 100)
        previous_status = job.status
        job.progress = round(progress, 2)
        job.status = _status_for(progress)
        status_changed = job.status != previous_status
        self._persist(job, force=status_changed or progress >= 100)
        if status_changed or _progress_step_changed(self._last_saved_progress.get(active_id, -1), progress):
            self.bus.publish("print_progress", self._public_progress(job))
        for mark in cues:
            if progress + 1e-6 >= mark and mark not in self._emitted[active_id]:
                self._emitted[active_id].add(mark)
                self.emotion.on_print_progress(mark, job.job_id)
        if progress >= 100:
            job.status = PrintStatus.done
            job.progress = 100
            self._persist(job, force=True)
            self.bus.publish("print_progress", self._public_progress(job))
            self._started_mono.pop(active_id, None)

    def update_runtime(self, values: dict[str, object]) -> dict[str, object]:
        cfg = self.settings.default_model.print_show
        allowed = {"grain", "camera_orbit", "reveal_lights", "default_duration_sec", "queue_jump"}
        for key, value in values.items():
            if key not in allowed or value is None:
                continue
            setattr(cfg, key, value)
        return {
            "grain": cfg.grain,
            "camera_orbit": cfg.camera_orbit,
            "reveal_lights": cfg.reveal_lights,
            "default_duration_sec": cfg.default_duration_sec,
            "queue_jump": cfg.queue_jump,
            "jump_min_style": cfg.jump_min_style.value,
            "show_min_sec": cfg.show_min_sec,
            "show_max_sec": cfg.show_max_sec,
        }

    def queue_ids(self) -> list[str]:
        return [
            job_id
            for job_id in self.order
            if self.jobs[job_id].status not in (PrintStatus.done, PrintStatus.failed)
        ]

    def public_jobs(self) -> list[dict]:
        ranked = {job_id: index for index, job_id in enumerate(self.order)}
        jobs = sorted(self.jobs.values(), key=lambda item: ranked.get(item.job_id, 0))
        return [self._public_progress(job) for job in jobs]

    def public_job(self, job_id: str) -> dict | None:
        job = self.jobs.get(job_id)
        if job is None:
            return None
        return self._public_progress(job)

    def _make(
        self,
        style: PrintStyle,
        avatar_type: AvatarType,
        duration: float,
        source_event_id: str | None,
        avatar_id: str | None,
        *,
        compensation: bool,
    ) -> PrintJob:
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
            timeline_ref=("compensate:" if compensation else "virtual:") + job_id,
            created_at=self.clock.time(),
        )
        self.jobs[job_id] = job
        self._emitted[job_id] = set()
        return job

    def _place(self, job: PrintJob) -> None:
        cfg = self.settings.default_model.print_show
        self.order.append(job.job_id)
        if not cfg.queue_jump or not can_jump_queue(job.style, cfg.jump_min_style):
            return
        active = self._active_id()
        self.order.remove(job.job_id)
        if active and active in self.order and active != job.job_id:
            self.order.insert(self.order.index(active) + 1, job.job_id)
        else:
            self.order.insert(0, job.job_id)

    def _active_id(self) -> str | None:
        for job_id in self.order:
            if self.jobs[job_id].status not in (PrintStatus.done, PrintStatus.failed):
                return job_id
        return None

    def _public_progress(self, job: PrintJob) -> dict:
        cfg = self.settings.default_model.print_show
        payload = dump_model(job)
        payload.update(
            print_uniforms(
                job.progress,
                grain=cfg.grain,
                orbit=cfg.camera_orbit,
                lights=cfg.reveal_lights,
                compensation=job.job_id in self._compensation,
            )
        )
        payload["queue_length"] = len(self.queue_ids())
        payload["active"] = self._active_id() == job.job_id
        payload["rebuild_geometry"] = False
        return payload

    def _persist(self, job: PrintJob, *, force: bool) -> None:
        previous = self._last_saved_progress.get(job.job_id, -1)
        if force or abs(job.progress - previous) >= 1:
            payload = dump_model(job)
            self.store.save_job(payload)
            self._last_saved_progress[job.job_id] = job.progress


def _status_for(progress: float) -> PrintStatus:
    if progress <= 0:
        return PrintStatus.queued
    if progress < 85:
        return PrintStatus.printing
    if progress < 95:
        return PrintStatus.refining
    if progress < 100:
        return PrintStatus.revealing
    return PrintStatus.done


def _progress_step_changed(previous: float, current: float) -> bool:
    if previous < 0:
        return True
    return int(previous) != int(current)
