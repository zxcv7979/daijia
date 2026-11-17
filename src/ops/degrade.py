"""负载降档、断线罐头动画、角色失败回退、WebGL 上下文恢复。"""

from __future__ import annotations

PRESET_FALLBACK = "preset-yuan"

# 断线时特效页本地循环这几帧，不向服务器要新网格。
CANNED_FRAMES = (
    {"name": "待机呼吸", "progress": 0.0, "hud": "画面保持"},
    {"name": "任务已接收", "progress": 5.0, "hud": "任务已接收"},
    {"name": "层层生长", "progress": 40.0, "hud": "层层生长"},
    {"name": "精修", "progress": 88.0, "hud": "精修"},
)


def load_level(cpu: float | None, gpu: float | None) -> int:
    """CPU 或 GPU 利用率超过 0.85 降一档，超过 0.95 降到最低。未知读数不强迫降档。"""

    hot = False
    very = False
    for value in (cpu, gpu):
        if value is None:
            continue
        if value >= 0.95:
            very = True
        elif value >= 0.85:
            hot = True
    if very:
        return 2
    if hot:
        return 1
    return 0


def combine_quality(frame_level: int, host_level: int) -> int:
    return max(0, min(2, max(frame_level, host_level)))


def canned_frame(step: int) -> dict[str, float | str | bool]:
    frame = dict(CANNED_FRAMES[step % len(CANNED_FRAMES)])
    frame["freeze"] = False
    frame["black"] = False
    frame["rebuild_geometry"] = False
    return frame


def context_recovery_plan() -> dict[str, object]:
    """丢失 WebGL 上下文后恢复同一套场景。网格对象保留，只重新上传一次。"""

    return {
        "action": "restore_context",
        "rebuild_renderer": True,
        "dispose_scene_graph": False,
        "per_frame_rebuild": False,
        "black_screen": False,
        "keep_progress": True,
    }
