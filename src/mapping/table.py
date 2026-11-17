"""把规范化事件解析成 L0-L4 档位。"""

from __future__ import annotations

from dataclasses import dataclass

from src.models import AvatarType, EmotionName, LiveEvent, PrintStyle
from src.settings import Settings, TierSpec, TriggerSpec


@dataclass
class Resolution:
    level: str
    priority: int
    emotion: EmotionName
    intensity: float
    fx: str
    atmosphere_only: bool
    hold_ms: int
    print_style: PrintStyle | None
    print_avatar: AvatarType | None
    fired: bool = True
    particles: int = 24
    secondary: bool = False
    beat: str = ""


class MappingTable:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def resolve(self, event: LiveEvent, highlight: str | None = None) -> Resolution | None:
        best: tuple[tuple[int, int], Resolution] | None = None
        for level, tier in self.settings.mappings_model.tiers.items():
            for trigger in tier.triggers:
                score = _score(trigger, event, highlight)
                if score < 0:
                    continue
                resolution = self._from_tier(level, tier, trigger.fx or tier.fx)
                key = (score, tier.priority)
                if best is None or key > best[0]:
                    best = (key, resolution)
        if best is None:
            return None
        return best[1]

    def tier(self, level: str) -> Resolution:
        try:
            spec = self.settings.mappings_model.tiers[level]
        except KeyError as exc:
            raise KeyError(f"未知档位 {level}") from exc
        return self._from_tier(level, spec, spec.fx)

    def _from_tier(self, level: str, tier: TierSpec, fx: str) -> Resolution:
        hold = tier.hold_ms
        if hold is None:
            hold = self.settings.default_model.emotion.hold_ms
        print_style = None
        print_avatar = None
        if tier.print_spec is not None:
            print_style = tier.print_spec.style
            print_avatar = tier.print_spec.avatar_type
        return Resolution(
            level=level,
            priority=tier.priority,
            emotion=tier.emotion,
            intensity=tier.intensity,
            fx=fx,
            atmosphere_only=tier.atmosphere_only,
            hold_ms=hold,
            print_style=print_style,
            print_avatar=print_avatar,
            particles=tier.particles,
            secondary=tier.secondary,
        )


def _score(trigger: TriggerSpec, event: LiveEvent, highlight: str | None) -> int:
    if trigger.type != event.type:
        return -1
    if trigger.highlight and trigger.highlight != highlight:
        return -1
    if trigger.price_min is not None and event.price < trigger.price_min:
        return -1
    if trigger.price_max is not None and event.price > trigger.price_max:
        return -1
    if trigger.combo_min is not None and event.combo_count < trigger.combo_min:
        return -1
    if trigger.keywords:
        text = event.text or ""
        if not any(word and word in text for word in trigger.keywords):
            return -1
    score = 1
    if trigger.keywords:
        score += 4
    if trigger.highlight:
        score += 10
    if trigger.price_min is not None:
        score += 3
    if trigger.price_max is not None:
        score += 2
    if trigger.combo_min is not None:
        score += 3
    if trigger.fx:
        score += 1
    return score
