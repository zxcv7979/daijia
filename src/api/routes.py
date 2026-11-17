"""管理接口。全部是模拟数据，不转发到任何直播平台。"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.adapters.sim_replay import SCENES
from src.models import AvatarType, EventType, PrintStyle, dump_model
from src.runtime import Context
from src.settings import ConfigError

router = APIRouter()


def _ctx(request: Request) -> Context:
    return request.app.state.ctx


class ReplayStartIn(BaseModel):
    file: str = "replay.jsonl"
    speed: Literal[1, 5, 20] = 1
    loop: bool = False


class SpeedIn(BaseModel):
    speed: Literal[1, 5, 20]


class SceneStartIn(BaseModel):
    name: Literal["small_gift_combo", "big_gift_rank1", "danmaku_flood"]
    speed: Literal[1, 5, 20] = 1
    loop: bool = False


class BurstIn(BaseModel):
    count: int = Field(default=200, ge=1, le=1000)
    window_sec: float = Field(default=1.0, gt=0, le=10)


class TriggerIn(BaseModel):
    level: Literal["L0", "L1", "L2", "L3", "L4"]


class MappingIn(BaseModel):
    yaml: str = Field(min_length=1, max_length=100_000)


class PrintIn(BaseModel):
    avatar_id: str | None = None
    avatar_type: AvatarType = AvatarType.stylized
    style: PrintStyle = PrintStyle.cartoon
    duration_sec: float | None = Field(default=None, gt=0, le=600)
    source_event_id: str | None = None


class CollectionIn(BaseModel):
    enabled: bool


class SimulateIn(BaseModel):
    source_msg_id: str | None = None
    type: EventType
    user_id: str = Field(min_length=1, max_length=128)
    nickname: str = Field(min_length=1, max_length=64)
    avatar_url: str | None = None
    gift_id: str | None = None
    gift_name: str | None = None
    combo_count: int = Field(default=1, ge=1, le=9999)
    price: float = Field(default=0, ge=0)
    text: str | None = None
    highlight: str | None = None
    ts: float | None = None
    raw_ref: str | None = None


@router.get("/api/health")
async def health(request: Request) -> dict[str, object]:
    ctx = _ctx(request)
    return {
        "ok": True,
        "collection_enabled": ctx.settings.collection_enabled(),
        "official_adapter": "disabled",
        "config_error": ctx.settings.last_error,
    }


@router.get("/api/metrics")
async def metrics(request: Request) -> dict[str, object]:
    return _ctx(request).stats.snapshot()


@router.get("/api/emotion")
async def emotion(request: Request) -> dict[str, object]:
    return _ctx(request).emotion.snapshot()


@router.post("/api/trigger")
async def trigger(body: TriggerIn, request: Request) -> dict[str, object]:
    return _ctx(request).emotion.trigger_level(body.level)


@router.get("/api/mappings")
async def get_mappings(request: Request) -> dict[str, object]:
    ctx = _ctx(request)
    return {"yaml": ctx.settings.mappings_text, "error": ctx.settings.last_error}


@router.put("/api/mappings")
async def put_mappings(body: MappingIn, request: Request) -> dict[str, object]:
    ctx = _ctx(request)
    try:
        ctx.settings.apply_mappings_text(body.yaml)
    except ConfigError as exc:
        # 非法 YAML 不能拖垮进程，旧映射继续生效。
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "error": None}


@router.get("/api/events")
async def list_events(request: Request, limit: int = 100) -> list[dict[str, object]]:
    return _ctx(request).store.list_events(limit)


@router.post("/api/events/simulate")
async def simulate(body: SimulateIn, request: Request) -> dict[str, object]:
    payload = body.model_dump()
    payload["adapter"] = "sim"
    result = await _ctx(request).ingest(payload)
    if not result.get("ok") and result.get("reason") == "rejected":
        raise HTTPException(status_code=400, detail="模拟事件无法解析")
    return result


@router.get("/api/replay")
async def replay_status(request: Request) -> dict[str, object]:
    return _ctx(request).replay.status()


@router.post("/api/replay/start")
async def replay_start(body: ReplayStartIn, request: Request) -> dict[str, object]:
    try:
        return await _ctx(request).replay.start_file(body.file, speed=body.speed, loop=body.loop)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/replay/stop")
async def replay_stop(request: Request) -> dict[str, object]:
    return await _ctx(request).replay.stop()


@router.post("/api/replay/speed")
async def replay_speed(body: SpeedIn, request: Request) -> dict[str, object]:
    ctx = _ctx(request)
    ctx.replay.set_speed(body.speed)
    return ctx.replay.status()


@router.post("/api/replay/burst")
async def replay_burst(body: BurstIn, request: Request) -> dict[str, object]:
    ctx = _ctx(request)
    before_received = ctx.stats.received
    before_dropped = ctx.stats.dropped
    before_published = ctx.stats.published
    try:
        pacing = await ctx.replay.burst(body.count, body.window_sec)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        **pacing,
        "received": ctx.stats.received - before_received,
        "dropped": ctx.stats.dropped - before_dropped,
        "published": ctx.stats.published - before_published,
    }


@router.get("/api/scenes")
async def scenes() -> list[dict[str, str]]:
    return [{"name": name, "title": meta["title"], "file": meta["file"]} for name, meta in SCENES.items()]


@router.post("/api/scenes/start")
async def scene_start(body: SceneStartIn, request: Request) -> dict[str, object]:
    try:
        return await _ctx(request).replay.start_scene(body.name, speed=body.speed, loop=body.loop)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/print-jobs")
async def list_jobs(request: Request) -> list[dict[str, object]]:
    return _ctx(request).printer.public_jobs()


@router.get("/api/print-jobs/{job_id}")
async def get_job(job_id: str, request: Request) -> dict[str, object]:
    job = _ctx(request).printer.public_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="找不到打印任务")
    return job


@router.post("/api/print-jobs")
async def create_job(body: PrintIn, request: Request) -> dict[str, object]:
    try:
        job = _ctx(request).printer.create(
            style=body.style,
            avatar_type=body.avatar_type,
            duration_sec=body.duration_sec,
            source_event_id=body.source_event_id,
            avatar_id=body.avatar_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return dump_model(job)


@router.get("/api/compliance")
async def compliance(request: Request) -> dict[str, object]:
    ctx = _ctx(request)
    return {
        "collection_enabled": ctx.settings.collection_enabled(),
        "official_adapter": "disabled",
        "note": "真实采集默认关闭。打开后只写审计日志，不会连接平台。",
    }


@router.post("/api/compliance/collection")
async def set_collection(body: CollectionIn, request: Request) -> dict[str, object]:
    return await _ctx(request).set_collection_enabled(body.enabled)


@router.get("/api/audit")
async def audit(request: Request, limit: int = 50) -> list[dict[str, object]]:
    return _ctx(request).store.list_audit(limit)
