"""去重、连击合并、200ms 同文聚合、昵称打码。"""

from __future__ import annotations

from src.models import EventType, RawIncoming, public_event
from src.normalize.pii import hash_user_id, mask_nickname
from src.normalize.pipeline import Normalizer
from src.settings import Settings


def _raw(**overrides) -> RawIncoming:
    data = {
        "adapter": "sim",
        "source_msg_id": "m1",
        "type": EventType.like,
        "user_id": "user-真实-42",
        "nickname": "小明",
        "ts": 1_700_000_000.0,
        "raw_ref": "internal-secret-ref",
    }
    data.update(overrides)
    return RawIncoming.model_validate(data)


def test_mask_nickname_keeps_first_character():
    assert mask_nickname("小明") == "小*"
    assert mask_nickname("小明同学") == "小***"
    assert mask_nickname("Tom") == "T**"
    assert mask_nickname("明") == "明"
    assert mask_nickname("  ") == "*"


def test_user_hash_uses_salt():
    assert hash_user_id("user-真实-42", "salt-a") != hash_user_id("user-真实-42", "salt-b")
    assert hash_user_id("user-真实-42", "salt-a") == hash_user_id("user-真实-42", "salt-a")
    assert "user-真实-42" not in hash_user_id("user-真实-42", "salt-a")


def test_dedup_by_source_msg_id_and_expiry(project):
    normalizer = Normalizer(Settings(project))
    first = normalizer.feed(_raw())
    again = normalizer.feed(_raw(ts=1_700_000_010.0))
    assert first.op.value == "new"
    assert again.op.value == "duplicate"
    later = normalizer.feed(_raw(ts=1_700_000_031.0))
    assert later.op.value == "new"
    assert later.event is not None and first.event is not None
    assert later.event.event_id != first.event.event_id


def test_dedup_hash_when_id_missing_uses_bucket_and_content(project):
    normalizer = Normalizer(Settings(project))
    base = dict(source_msg_id=None, type=EventType.danmaku, text="同样一句", user_id="u1", nickname="甲")
    first = normalizer.feed(_raw(**base, ts=100.00))
    same_bucket = normalizer.feed(_raw(**base, ts=100.05))
    next_bucket = normalizer.feed(_raw(**base, ts=100.15))
    other = dict(base)
    other["text"] = "另一句"
    other["ts"] = 100.16
    other_text = normalizer.feed(_raw(**other))
    assert first.op.value == "new"
    assert same_bucket.op.value == "duplicate"
    # 150ms 后进入下一个 100ms 桶，且仍在 200ms 聚合窗口内，所以是合并而不是新的重复丢弃。
    assert next_bucket.op.value == "update"
    assert next_bucket.event is not None and first.event is not None
    assert next_bucket.event.event_id == first.event.event_id
    assert next_bucket.event.combo_count == 2
    assert other_text.op.value == "new"


def test_combo_merge_window(project):
    normalizer = Normalizer(Settings(project))
    gift = dict(
        type=EventType.gift,
        user_id="combo-user",
        nickname="连击手",
        gift_id="local_rose",
        gift_name="小花",
        price=1,
        text=None,
    )
    first = normalizer.feed(_raw(**gift, source_msg_id="g1", ts=50.0))
    merged = normalizer.feed(_raw(**gift, source_msg_id="g2", ts=50.4))
    assert merged.op.value == "update"
    assert merged.event is not None and first.event is not None
    assert merged.event.event_id == first.event.event_id
    assert merged.event.combo_count == 2
    separate = normalizer.feed(_raw(**gift, source_msg_id="g3", ts=50.4 + 0.9))
    assert separate.op.value == "new"
    assert separate.event is not None
    assert separate.event.event_id != first.event.event_id
    other = dict(gift)
    other.update(source_msg_id="g4", gift_id="local_other", ts=50.45)
    other_gift = normalizer.feed(_raw(**other))
    assert other_gift.op.value == "new"


def test_danmaku_aggregation_is_200ms_not_2s(project):
    normalizer = Normalizer(Settings(project))
    assert normalizer.aggregate_window_ms == 200
    text = dict(
        type=EventType.danmaku,
        user_id="u",
        nickname="甲",
        text="666666",
    )
    # 带上来源 ID，避免无 ID 时先被 100ms 桶去重吃掉。
    first = normalizer.feed(_raw(**text, source_msg_id="d1", ts=10.0))
    within_payload = dict(text)
    within_payload.update(source_msg_id="d2", user_id="other", nickname="乙", ts=10.2)
    within = normalizer.feed(_raw(**within_payload))
    assert within.op.value == "update"
    assert within.event is not None and first.event is not None
    assert within.event.event_id == first.event.event_id
    assert within.event.combo_count == 2
    # 若窗口被误配成 2 秒，1.5 秒后的同文仍会合并。这里必须拆开。
    later = normalizer.feed(_raw(**text, source_msg_id="d3", ts=11.5))
    assert later.op.value == "new"
    assert later.event is not None
    assert later.event.event_id != first.event.event_id
    edge = normalizer.feed(_raw(**text, source_msg_id="d5", ts=20.0))
    just_over = normalizer.feed(_raw(**text, source_msg_id="d4", ts=20.35))
    assert edge.op.value == "new"
    assert just_over.op.value == "new"
    assert just_over.event is not None and edge.event is not None
    assert just_over.event.event_id != edge.event.event_id


def test_masking_strips_raw_identity(project):
    normalizer = Normalizer(Settings(project))
    result = normalizer.feed(
        _raw(
            avatar_url="https://cdn.example/user-真实-42/a.png",
            text="你好",
            type=EventType.danmaku,
        )
    )
    event = result.event
    assert event is not None
    assert event.nickname_masked == "小*"
    assert event.user_id_hash != "user-真实-42"
    assert "user-真实-42" not in event.user_id_hash
    assert event.avatar_url is None
    assert event.raw_ref == "internal-secret-ref"
    public = public_event(event)
    assert "raw_ref" not in public
    blob = str(public)
    assert "user-真实-42" not in blob
    assert "internal-secret-ref" not in blob
    assert "小明" not in blob
    assert public["nickname_masked"] == "小*"
