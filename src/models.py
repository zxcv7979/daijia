"""对外数据模型。WebSocket 与管理接口只序列化白名单字段。"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EventType(str, Enum):
    danmaku = "danmaku"
    comment = "comment"
    gift = "gift"
    combo = "combo"
    enter = "enter"
    like = "like"
    follow = "follow"


class EmotionName(str, Enum):
    ambient = "ambient"
    joy = "joy"
    hype = "hype"
    awe = "awe"
    tender = "tender"
    alert = "alert"


class AvatarType(str, Enum):
    real = "real"
    stylized = "stylized"


class PrintStyle(str, Enum):
    realistic = "realistic"
    hologram = "hologram"
    cartoon = "cartoon"


class PrintStatus(str, Enum):
    queued = "queued"
    printing = "printing"
    refining = "refining"
    revealing = "revealing"
    done = "done"
    failed = "failed"


class NormOp(str, Enum):
    new = "new"
    update = "update"
    duplicate = "duplicate"


# 推给浏览器的事件字段。raw_ref 与任何原始用户标识都不在此列。
PUBLIC_EVENT_FIELDS = (
    "event_id",
    "type",
    "user_id_hash",
    "nickname_masked",
    "avatar_url",
    "gift_id",
    "gift_name",
    "combo_count",
    "price",
    "ts",
    "text",
)


class LiveEvent(BaseModel):
    event_id: str
    type: EventType
    user_id_hash: str
    nickname_masked: str
    avatar_url: str | None = None
    gift_id: str | None = None
    gift_name: str | None = None
    combo_count: int = Field(default=1, ge=1)
    # 本地档位分，不是平台礼物价格。
    price: float = Field(default=0, ge=0)
    ts: float
    # 展示文案（弹幕/评论）。不是平台原始报文。
    text: str | None = None
    # 仅服务端排查用，禁止进入 WS 与 HTTP 响应。
    raw_ref: str | None = Field(default=None, exclude=True)


class EmotionState(BaseModel):
    emotion: EmotionName
    intensity: float = Field(ge=0, le=1)
    priority: int
    source_event: str | None = None
    started_at: float
    decay_half_life: float
    is_ducking: bool = False


class FxCue(BaseModel):
    cue_id: str
    level: str
    fx: str
    emotion: EmotionName
    intensity: float = Field(ge=0, le=1)
    priority: int
    source_event_id: str | None = None
    ttl_ms: int = 2000


class PrintJob(BaseModel):
    job_id: str
    avatar_id: str
    avatar_type: AvatarType
    source_event_id: str | None = None
    style: PrintStyle
    status: PrintStatus
    progress: float = Field(ge=0, le=100)
    duration_sec: float = Field(gt=0)
    timeline_ref: str | None = None
    created_at: float


class RawIncoming(BaseModel):
    """模拟源进入规范化之前的内部结构。不对外发送。"""

    model_config = {"extra": "ignore"}

    adapter: str = "sim"
    source_msg_id: str | None = None
    type: EventType
    user_id: str = Field(min_length=1, max_length=128)
    nickname: str = Field(min_length=1, max_length=64)
    avatar_url: str | None = None
    gift_id: str | None = None
    gift_name: str | None = None
    combo_count: int = Field(default=1, ge=1, le=9999)
    price: float = Field(default=0, ge=0, le=1_000_000)
    text: str | None = None
    ts: float | None = None
    highlight: str | None = None
    raw_ref: str | None = None


def dump_model(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")


def public_event(event: LiveEvent) -> dict[str, Any]:
    """白名单序列化。调用方应只把返回值写入 WS、HTTP 和 SQLite。"""

    data = dump_model(event)
    return {key: data[key] for key in PUBLIC_EVENT_FIELDS if key in data}
