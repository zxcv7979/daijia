"""切换角色时的画面策略：新模型没好就留着上一帧。"""

from __future__ import annotations


def switch_plan(*, current: str | None, incoming: str, loaded: bool) -> str:
    if not loaded:
        return "keep-current"
    if current == incoming:
        return "same"
    return "crossfade"
