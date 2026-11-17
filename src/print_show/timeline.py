"""虚拟打印时间轴。只算 uniforms，不创建网格。"""

from __future__ import annotations

from src.models import PrintStyle

STYLE_RANK = {
    PrintStyle.cartoon: 1,
    PrintStyle.realistic: 2,
    PrintStyle.hologram: 3,
}


def phase_of(progress: float) -> str:
    if progress < 5:
        return "preheat"
    if progress < 85:
        return "layer"
    if progress < 95:
        return "refine"
    if progress < 100:
        return "reveal"
    return "done"


def hud_for(progress: float, *, compensation: bool = False) -> str:
    if compensation and progress < 5:
        return "补偿重打"
    phase = phase_of(progress)
    if phase == "preheat":
        return "任务已接收"
    if phase == "layer":
        if progress >= 90:
            return "屏息"
        return "层层生长"
    if phase == "refine":
        return "屏息" if progress >= 90 else "精修"
    if phase == "reveal":
        return "揭晓"
    return "完成"


def clip_y(progress: float) -> float:
    """层生长把世界 Y 裁切从 -1 推到 1。预热停在底部，精修后完全露出。"""

    if progress < 5:
        return -1.0
    if progress >= 85:
        return 1.0
    return -1.0 + (progress - 5) / 80.0 * 2.0


def print_uniforms(
    progress: float,
    *,
    grain: float = 0.4,
    orbit: float = 1.0,
    lights: float = 1.0,
    compensation: bool = False,
) -> dict[str, float | str | bool]:
    phase = phase_of(progress)
    growing = 5 <= progress < 85
    return {
        "phase": phase,
        "clip_y": clip_y(progress),
        "grain": grain if growing else grain * 0.15,
        "scanline": 1.0 if phase in {"layer", "refine"} else 0.0,
        "wire": 1.0 if phase == "refine" and progress < 92 else 0.0,
        "lights": lights if progress >= 95 else (0.35 if progress > 0 else 0.0),
        "orbit": orbit if progress >= 95 else 0.0,
        "burst": 1.0 if progress >= 100 else 0.0,
        "hold_breath": 1.0 if progress >= 90 else 0.0,
        "hud": hud_for(progress, compensation=compensation),
        "rebuild_geometry": False,
    }


def can_jump_queue(style: PrintStyle, minimum: PrintStyle) -> bool:
    """只有达到门槛的风格能插到正在打印的任务后面，不能打断热床上的那一件。"""

    return STYLE_RANK[style] >= STYLE_RANK[minimum]
