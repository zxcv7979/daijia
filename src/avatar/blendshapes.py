"""ARKit 52 个口型名，以及情绪到权重的本地映射。"""

from __future__ import annotations

ARKIT_52: tuple[str, ...] = (
    "eyeBlinkLeft",
    "eyeBlinkRight",
    "eyeLookDownLeft",
    "eyeLookDownRight",
    "eyeLookInLeft",
    "eyeLookInRight",
    "eyeLookOutLeft",
    "eyeLookOutRight",
    "eyeLookUpLeft",
    "eyeLookUpRight",
    "eyeSquintLeft",
    "eyeSquintRight",
    "eyeWideLeft",
    "eyeWideRight",
    "jawForward",
    "jawLeft",
    "jawRight",
    "jawOpen",
    "mouthClose",
    "mouthFunnel",
    "mouthPucker",
    "mouthLeft",
    "mouthRight",
    "mouthSmileLeft",
    "mouthSmileRight",
    "mouthFrownLeft",
    "mouthFrownRight",
    "mouthDimpleLeft",
    "mouthDimpleRight",
    "mouthStretchLeft",
    "mouthStretchRight",
    "mouthRollLower",
    "mouthRollUpper",
    "mouthShrugLower",
    "mouthShrugUpper",
    "mouthPressLeft",
    "mouthPressRight",
    "mouthLowerDownLeft",
    "mouthLowerDownRight",
    "mouthUpperUpLeft",
    "mouthUpperUpRight",
    "browDownLeft",
    "browDownRight",
    "browInnerUp",
    "browOuterUpLeft",
    "browOuterUpRight",
    "cheekPuff",
    "cheekSquintLeft",
    "cheekSquintRight",
    "noseSneerLeft",
    "noseSneerRight",
    "tongueOut",
)

# 只写非零项。其余名字补 0，保证返回表始终有 52 个键。
_EMOTIONS: dict[str, dict[str, float]] = {
    "ambient": {"mouthClose": 0.15, "browInnerUp": 0.05},
    "joy": {
        "mouthSmileLeft": 0.85,
        "mouthSmileRight": 0.85,
        "cheekSquintLeft": 0.35,
        "cheekSquintRight": 0.35,
        "mouthDimpleLeft": 0.2,
        "mouthDimpleRight": 0.2,
    },
    "hype": {
        "jawOpen": 0.45,
        "mouthFunnel": 0.25,
        "eyeWideLeft": 0.4,
        "eyeWideRight": 0.4,
        "browOuterUpLeft": 0.5,
        "browOuterUpRight": 0.5,
    },
    "awe": {
        "jawOpen": 0.7,
        "eyeWideLeft": 0.8,
        "eyeWideRight": 0.8,
        "browInnerUp": 0.6,
        "browOuterUpLeft": 0.4,
        "browOuterUpRight": 0.4,
    },
    "tender": {
        "mouthSmileLeft": 0.35,
        "mouthSmileRight": 0.35,
        "eyeSquintLeft": 0.15,
        "eyeSquintRight": 0.15,
        "browInnerUp": 0.2,
    },
    "alert": {
        "browDownLeft": 0.7,
        "browDownRight": 0.7,
        "mouthFrownLeft": 0.45,
        "mouthFrownRight": 0.45,
        "eyeSquintLeft": 0.3,
        "eyeSquintRight": 0.3,
        "noseSneerLeft": 0.2,
        "noseSneerRight": 0.2,
    },
}


def weights_for_emotion(emotion: str, intensity: float, *, blink: float = 0.0, lip: float = 0.0) -> dict[str, float]:
    """情绪权重乘上强度，再叠上眨眼和口型钩子。"""

    amount = max(0.0, min(1.0, intensity))
    weights = {name: 0.0 for name in ARKIT_52}
    for name, value in _EMOTIONS.get(emotion, _EMOTIONS["ambient"]).items():
        weights[name] = max(0.0, min(1.0, value * amount))
    blink = max(0.0, min(1.0, blink))
    lip = max(0.0, min(1.0, lip))
    weights["eyeBlinkLeft"] = max(weights["eyeBlinkLeft"], blink)
    weights["eyeBlinkRight"] = max(weights["eyeBlinkRight"], blink)
    weights["jawOpen"] = max(weights["jawOpen"], lip)
    return weights
