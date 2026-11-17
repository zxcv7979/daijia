"""去重、连击合并、同文弹幕 200ms 聚合、脱敏。

热路径是同步的：一条输入得到 new / update / duplicate，不会因为队列满而丢弃。
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

from src.models import EventType, LiveEvent, NormOp, RawIncoming
from src.normalize.pii import hash_user_id, mask_nickname
from src.settings import Settings

_GIFT_TYPES = {EventType.gift, EventType.combo}
_TEXT_TYPES = {EventType.danmaku, EventType.comment}


@dataclass
class NormResult:
    op: NormOp
    event: LiveEvent | None = None
    source_key: str = ""


class Normalizer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._seen: dict[str, int] = {}
        # 文案 -> (事件, 最近一条的毫秒时间戳)
        self._texts: dict[str, tuple[LiveEvent, int]] = {}
        # (用户哈希, 礼物键) -> (事件, 最近一条的毫秒时间戳)
        self._combos: dict[tuple[str, str], tuple[LiveEvent, int]] = {}

    @property
    def aggregate_window_ms(self) -> int:
        return self.settings.default_model.normalize.danmaku_aggregate_window_ms

    @property
    def combo_window_ms(self) -> int:
        return self.settings.default_model.normalize.combo_merge_window_ms

    def feed(self, raw: RawIncoming) -> NormResult:
        if raw.ts is None:
            raise ValueError("规范化前必须带 ts")
        ts_ms = _ms(raw.ts)
        source_key = self._dedup_key(raw, ts_ms)
        if self._is_duplicate(source_key, ts_ms):
            return NormResult(op=NormOp.duplicate, source_key=source_key)

        if raw.type in _TEXT_TYPES:
            return self._aggregate_text(raw, source_key, ts_ms)
        if raw.type in _GIFT_TYPES:
            return self._merge_combo(raw, source_key, ts_ms)
        return NormResult(op=NormOp.new, event=self._build(raw), source_key=source_key)

    def _aggregate_text(self, raw: RawIncoming, source_key: str, ts_ms: int) -> NormResult:
        # 产品约束：同文窗口就是 200ms。这里再读一次配置，热加载后立即生效。
        window = self.aggregate_window_ms
        if window != 200:
            raise RuntimeError("弹幕同文聚合窗口必须为 200ms")
        text_key = _normalize_text(raw.text or "")
        if not text_key:
            return NormResult(op=NormOp.new, event=self._build(raw), source_key=source_key)
        slot = self._texts.get(text_key)
        if slot is not None and ts_ms - slot[1] <= window:
            event = slot[0]
            event.combo_count += max(1, raw.combo_count)
            event.ts = float(raw.ts or event.ts)
            self._texts[text_key] = (event, ts_ms)
            return NormResult(op=NormOp.update, event=event, source_key=source_key)
        event = self._build(raw)
        self._texts[text_key] = (event, ts_ms)
        return NormResult(op=NormOp.new, event=event, source_key=source_key)

    def _merge_combo(self, raw: RawIncoming, source_key: str, ts_ms: int) -> NormResult:
        user_hash = hash_user_id(raw.user_id, self.settings.salt)
        gift_key = raw.gift_id or raw.gift_name or raw.type.value
        slot_key = (user_hash, gift_key)
        window = self.combo_window_ms
        slot = self._combos.get(slot_key)
        if slot is not None and ts_ms - slot[1] <= window:
            event = slot[0]
            event.combo_count += max(1, raw.combo_count)
            event.ts = float(raw.ts or event.ts)
            if raw.price > event.price:
                event.price = raw.price
            self._combos[slot_key] = (event, ts_ms)
            return NormResult(op=NormOp.update, event=event, source_key=source_key)
        event = self._build(raw)
        self._combos[slot_key] = (event, ts_ms)
        return NormResult(op=NormOp.new, event=event, source_key=source_key)

    def _build(self, raw: RawIncoming) -> LiveEvent:
        avatar = raw.avatar_url
        if avatar and raw.user_id and raw.user_id in avatar:
            avatar = None
        text = (raw.text or "").strip()
        if len(text) > 80:
            text = text[:80]
        return LiveEvent(
            event_id=uuid.uuid4().hex,
            type=raw.type,
            user_id_hash=hash_user_id(raw.user_id, self.settings.salt),
            nickname_masked=mask_nickname(raw.nickname),
            avatar_url=avatar or None,
            gift_id=raw.gift_id,
            gift_name=raw.gift_name,
            combo_count=max(1, raw.combo_count),
            price=raw.price,
            ts=float(raw.ts or 0),
            text=text or None,
            raw_ref=raw.raw_ref,
        )

    def _dedup_key(self, raw: RawIncoming, ts_ms: int) -> str:
        if raw.source_msg_id:
            return f"{raw.adapter}:{raw.source_msg_id}"
        bucket_ms = self.settings.default_model.normalize.ts_bucket_ms
        bucket = ts_ms // bucket_ms
        if raw.type in _GIFT_TYPES:
            content = f"{raw.gift_id or ''}|{raw.price}|{raw.combo_count}"
        else:
            content = _normalize_text(raw.text or "")
        material = f"{raw.type.value}|{raw.user_id}|{bucket}|{content}"
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
        return f"{raw.adapter}:h:{digest}"

    def _is_duplicate(self, key: str, ts_ms: int) -> bool:
        window_ms = self.settings.default_model.normalize.dedup_window_sec * 1000
        if len(self._seen) > 8000:
            cutoff = ts_ms - window_ms
            self._seen = {item: seen for item, seen in self._seen.items() if seen >= cutoff}
        previous = self._seen.get(key)
        if previous is not None and ts_ms - previous <= window_ms:
            return True
        self._seen[key] = ts_ms
        return False


def _ms(ts: float) -> int:
    return int(round(ts * 1000))


def _normalize_text(text: str) -> str:
    return text.strip().casefold()
