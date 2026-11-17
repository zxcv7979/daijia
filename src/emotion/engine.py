"""事件 → 档位 → 情绪。

上升 150–300ms，保持，然后按 4–8 秒半衰期指数衰减。
高优先级可以压低（duck）低优先级。弹幕是氛围，不抢走礼物主秀。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from src.bus.event_bus import EventBus
from src.clock import SystemClock
from src.mapping.table import MappingTable, Resolution
from src.models import EmotionName, EmotionState, FxCue, LiveEvent, dump_model
from src.settings import Settings


def intensity_at(
    elapsed_ms: float,
    target: float,
    rise_ms: int,
    hold_ms: int,
    half_life_s: float,
) -> float:
    """上升 → 保持 → 指数衰减。elapsed 为负时视为还没开始。"""

    if elapsed_ms <= 0 or target <= 0:
        return 0.0
    if elapsed_ms < rise_ms:
        return target * (elapsed_ms / rise_ms)
    after_rise = elapsed_ms - rise_ms
    if after_rise < hold_ms:
        return target
    decay_s = (after_rise - hold_ms) / 1000
    return target * (0.5 ** (decay_s / half_life_s))


def phase_at(elapsed_ms: float, rise_ms: int, hold_ms: int) -> str:
    if elapsed_ms < rise_ms:
        return "rise"
    if elapsed_ms < rise_ms + hold_ms:
        return "hold"
    return "decay"


@dataclass
class _Cue:
    cue_id: str
    level: str
    fx: str
    emotion: EmotionName
    target: float
    priority: int
    # 同优先级时，后触发的覆盖先触发的（打印里程碑、手动挡位）。
    seq: int
    source_event: str | None
    started_mono: float
    started_wall: float
    rise_ms: int
    hold_ms: int
    half_life: float
    atmosphere_only: bool
    ttl_ms: int = 2000

    def elapsed_ms(self, now_mono: float) -> float:
        return (now_mono - self.started_mono) * 1000

    def intensity(self, now_mono: float) -> float:
        value = intensity_at(self.elapsed_ms(now_mono), self.target, self.rise_ms, self.hold_ms, self.half_life)
        return max(0.0, min(1.0, value))

    def phase(self, now_mono: float) -> str:
        return phase_at(self.elapsed_ms(now_mono), self.rise_ms, self.hold_ms)


@dataclass
class EmotionEngine:
    settings: Settings
    bus: EventBus
    table: MappingTable
    clock: SystemClock
    cues: list[_Cue] = field(default_factory=list)
    _last_fire_mono: dict[str, float] = field(default_factory=dict)
    _idle_started: float | None = None
    _seq: int = 0

    def handle(self, event: LiveEvent, *, highlight: str | None = None, op: str = "new") -> Resolution | None:
        if op == "update" and self._refresh_existing(event):
            self.publish_state()
            # 连击更新不重复开打印任务。
            return Resolution(
                level="",
                priority=0,
                emotion=EmotionName.ambient,
                intensity=0,
                fx="",
                atmosphere_only=True,
                hold_ms=0,
                print_style=None,
                print_avatar=None,
                fired=False,
            )
        resolution = self.table.resolve(event, highlight)
        if resolution is None:
            return None
        self._activate(resolution, source_event=event.event_id, bypass_cooldown=False)
        return resolution

    def trigger_level(self, level: str) -> dict[str, object]:
        # 管理页上的手动挡位是操作员覆盖：直接换上这一档，避免被仍在衰减的高优先级观众事件挡住。
        self.cues.clear()
        resolution = self.table.tier(level)
        source = f"manual-{level}-{uuid.uuid4().hex[:8]}"
        self._activate(resolution, source_event=source, bypass_cooldown=True)
        fx = self._latest_fx()
        return {"emotion": self.snapshot(), "fx_cue": fx}

    def force_emotion(self, name: EmotionName, intensity: float) -> dict[str, object]:
        """调试台滑块：直接铺一层手动情绪，方便 OBS 预览。"""

        self.cues.clear()
        resolution = Resolution(
            level="slider",
            priority=9,
            emotion=name,
            intensity=max(0.0, min(1.0, intensity)),
            fx="manual_slider",
            atmosphere_only=False,
            hold_ms=4000,
            print_style=None,
            print_avatar=None,
            particles=36,
            secondary=False,
        )
        self._activate(resolution, source_event="slider", bypass_cooldown=True)
        return {"emotion": self.snapshot(), "fx_cue": self._latest_fx()}

    def on_print_progress(self, percent: int, job_id: str) -> Resolution | None:
        table = self.settings.default_model.print_show.cue_table
        cue_cfg = table.get(percent) or table.get(int(percent))
        if cue_cfg is None:
            return None
        cfg = self.settings.default_model
        resolution = Resolution(
            level=f"P{percent}",
            priority=cfg.print_show.cue_priority,
            emotion=cue_cfg.emotion,
            intensity=cue_cfg.intensity,
            fx=cue_cfg.fx,
            atmosphere_only=False,
            hold_ms=cfg.print_show.cue_hold_ms,
            print_style=None,
            print_avatar=None,
        )
        self._activate(resolution, source_event=job_id, bypass_cooldown=True)
        return resolution

    def snapshot(self) -> dict[str, object]:
        state, phase, active = self._sample()
        payload = dump_model(state)
        payload["phase"] = phase
        payload["active"] = active
        return payload

    def publish_state(self) -> dict[str, object]:
        payload = self.snapshot()
        self.bus.publish("emotion", payload)
        return payload

    def _activate(self, resolution: Resolution, *, source_event: str | None, bypass_cooldown: bool) -> None:
        now_mono = self.clock.monotonic()
        if not bypass_cooldown and self._cooling(resolution.level, now_mono):
            resolution.fired = False
            return
        dominant = self._dominant(now_mono)
        # 弹幕/评论只铺氛围，不能把正在进行的礼物主秀换掉。
        if (
            resolution.atmosphere_only
            and dominant is not None
            and not dominant.atmosphere_only
            and dominant.priority > resolution.priority
        ):
            added = self._add_cue(resolution, source_event, now_mono, allow_evict=False)
            resolution.fired = added
            if added:
                if not bypass_cooldown:
                    self._last_fire_mono[resolution.level] = now_mono
                self._emit_fx(resolution, source_event)
                self.publish_state()
            return
        added = self._add_cue(resolution, source_event, now_mono, allow_evict=True)
        resolution.fired = added
        if not added:
            return
        # 手动挡位不写入冷却，避免操作员预览把随后的观众事件挡掉。
        if not bypass_cooldown:
            self._last_fire_mono[resolution.level] = now_mono
        self._emit_fx(resolution, source_event)
        self.publish_state()

    def _refresh_existing(self, event: LiveEvent) -> bool:
        for cue in self.cues:
            if cue.source_event != event.event_id:
                continue
            cue.hold_ms = min(cue.hold_ms + 200, 8000)
            cue.target = min(1.0, cue.target + 0.04)
            self._emit_fx(
                Resolution(
                    level=cue.level,
                    priority=cue.priority,
                    emotion=cue.emotion,
                    intensity=cue.target,
                    fx=cue.fx,
                    atmosphere_only=cue.atmosphere_only,
                    hold_ms=cue.hold_ms,
                    print_style=None,
                    print_avatar=None,
                ),
                event.event_id,
            )
            return True
        return False

    def _add_cue(
        self,
        resolution: Resolution,
        source_event: str | None,
        now_mono: float,
        *,
        allow_evict: bool,
    ) -> bool:
        cfg = self.settings.default_model.emotion
        if len(self.cues) >= cfg.max_on_screen:
            if not allow_evict:
                return False
            lower = [cue for cue in self.cues if cue.priority < resolution.priority]
            if not lower:
                return False
            victim = min(lower, key=lambda cue: (cue.priority, cue.seq))
            self.cues.remove(victim)
        rise_ms = cfg.rise_ms
        self._seq += 1
        self.cues.append(
            _Cue(
                cue_id=uuid.uuid4().hex,
                level=resolution.level,
                fx=resolution.fx,
                emotion=resolution.emotion,
                target=resolution.intensity,
                priority=resolution.priority,
                seq=self._seq,
                source_event=source_event,
                started_mono=now_mono,
                started_wall=self.clock.time(),
                rise_ms=rise_ms,
                hold_ms=resolution.hold_ms,
                half_life=cfg.decay_half_life_s,
                atmosphere_only=resolution.atmosphere_only,
            )
        )
        return True

    def _emit_fx(self, resolution: Resolution, source_event: str | None) -> dict[str, object]:
        cue = FxCue(
            cue_id=uuid.uuid4().hex,
            level=resolution.level or "update",
            fx=resolution.fx or "combo_tick",
            emotion=resolution.emotion,
            intensity=max(0.0, min(1.0, resolution.intensity)),
            priority=resolution.priority,
            source_event_id=source_event,
            ttl_ms=2000,
        )
        payload = dump_model(cue)
        payload["particles"] = resolution.particles
        payload["secondary"] = resolution.secondary
        payload["print"] = resolution.print_style is not None
        self.bus.publish("fx_cue", payload)
        return payload

    def _latest_fx(self) -> dict[str, object] | None:
        for message in reversed(self.bus.buffered_messages()):
            if message["kind"] == "fx_cue":
                return message["data"]
        return None

    def _cooling(self, level: str, now_mono: float) -> bool:
        if not level:
            return False
        last = self._last_fire_mono.get(level)
        if last is None:
            return False
        cooldown_ms = self.settings.default_model.emotion.cooldowns_ms.get(level, 0)
        return (now_mono - last) * 1000 < cooldown_ms

    def _dominant(self, now_mono: float) -> _Cue | None:
        living = [cue for cue in self.cues if not self._expired(cue, now_mono)]
        if not living:
            return None
        return max(living, key=lambda cue: (cue.priority, cue.seq))

    def _expired(self, cue: _Cue, now_mono: float) -> bool:
        return cue.phase(now_mono) == "decay" and cue.intensity(now_mono) < 0.03

    def _sample(self) -> tuple[EmotionState, str, list[dict[str, object]]]:
        now_mono = self.clock.monotonic()
        self.cues = [cue for cue in self.cues if not self._expired(cue, now_mono)]
        half_life = self.settings.default_model.emotion.decay_half_life_s
        ducking_on = self.settings.default_model.emotion.ducking.enabled
        if not self.cues:
            if self._idle_started is None:
                self._idle_started = self.clock.time()
            state = EmotionState(
                emotion=EmotionName.ambient,
                intensity=0.0,
                priority=0,
                source_event=None,
                started_at=self._idle_started,
                decay_half_life=half_life,
                is_ducking=False,
            )
            return state, "idle", []
        self._idle_started = None
        dominant = max(self.cues, key=lambda cue: (cue.priority, cue.seq))
        is_ducking = ducking_on and any(cue.priority < dominant.priority for cue in self.cues)
        state = EmotionState(
            emotion=dominant.emotion,
            intensity=dominant.intensity(now_mono),
            priority=dominant.priority,
            source_event=dominant.source_event,
            started_at=dominant.started_wall,
            decay_half_life=dominant.half_life,
            is_ducking=is_ducking,
        )
        active = []
        for cue in self.cues:
            active.append(
                {
                    "level": cue.level,
                    "emotion": cue.emotion.value,
                    "priority": cue.priority,
                    "intensity": round(cue.intensity(now_mono), 3),
                    "ducked": ducking_on and cue.cue_id != dominant.cue_id and cue.priority < dominant.priority,
                    "source_event": cue.source_event,
                }
            )
        return state, dominant.phase(now_mono), active
