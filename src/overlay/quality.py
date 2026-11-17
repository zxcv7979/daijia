"""60fps 保护：帧时间超预算就降档，粒子和同时在场的特效有硬上限。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class QualityState:
    level: int = 0
    over: int = 0
    under: int = 0

    @property
    def downshifted(self) -> bool:
        return self.level > 0


def step_quality(
    state: QualityState,
    frame_ms: float,
    *,
    frame_budget_ms: float = 12.0,
    recover_under_ms: float = 10.0,
    downshift_after_frames: int = 8,
    recover_after_frames: int = 45,
) -> QualityState:
    """level 0 是满质量，1 减半粒子并跳过次要特效，2 再减半。"""

    if frame_ms > frame_budget_ms:
        state.over += 1
        state.under = 0
        if state.over >= downshift_after_frames and state.level < 2:
            state.level += 1
            state.over = 0
    elif frame_ms < recover_under_ms:
        state.under += 1
        state.over = 0
        if state.under >= recover_after_frames and state.level > 0:
            state.level -= 1
            state.under = 0
    else:
        state.over = 0
        state.under = 0
    return state


def particle_budget(level: int, requested: int, hard_cap: int = 20_000) -> int:
    scale = (1.0, 0.5, 0.25)[max(0, min(2, level))]
    return max(0, min(hard_cap, int(requested * scale)))


def admit_fx(active: int, cap: int = 8) -> bool:
    return active < cap


def skip_secondary(level: int, secondary: bool) -> bool:
    return secondary and level >= 1


def apply_load(frame_level: int, cpu: float | None = None, gpu: float | None = None) -> int:
    """帧时间降档和主机负载取更严的一档。"""

    from src.ops.degrade import combine_quality, load_level

    return combine_quality(frame_level, load_level(cpu, gpu))
