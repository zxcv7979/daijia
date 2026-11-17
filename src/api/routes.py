"""管理接口。全部是模拟数据，不转发到任何直播平台。"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.adapters.sim_replay import SCENES
from src.models import AvatarType, EmotionName, EventType, PrintStyle, dump_model
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


class RealSourceIn(BaseModel):
    enabled: bool
    confirm: bool = False


class RawIn(BaseModel):
    adapter: str = "mock"
    payload: dict[str, object]


class EmotionSliderIn(BaseModel):
    emotion: EmotionName
    intensity: float = Field(ge=0, le=1)


class OverlayControlIn(BaseModel):
    mute: bool | None = None
    seek: float | None = Field(default=None, ge=0, le=1)
    clear_seek: bool = False


class OverlayStatsIn(BaseModel):
    fps: float = 0
    frame_ms: float = 0
    particles: int = 0
    fx: int = 0
    downshifted: bool = False
    level: int = 0
    heap: int = 0
    renderer: str = "none"


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
    return _ctx(request).compliance_view()


@router.post("/api/compliance/collection")
async def set_collection(body: CollectionIn, request: Request) -> dict[str, object]:
    return await _ctx(request).set_collection_enabled(body.enabled)


@router.post("/api/compliance/real-source")
async def set_real_source(body: RealSourceIn, request: Request) -> dict[str, object]:
    result = await _ctx(request).set_real_source(body.enabled, body.confirm)
    status = int(result.pop("status"))
    if status != 200:
        raise HTTPException(status_code=status, detail=str(result.get("detail")))
    return result


@router.get("/api/adapters")
async def list_adapters(request: Request) -> dict[str, object]:
    ctx = _ctx(request)
    return {
        "real_source_active": ctx.sources.real_source_active,
        "adapters": ctx.sources.describe(),
        "governor": ctx.sources.governor.snapshot(),
    }


@router.post("/api/adapters/{name}/start")
async def start_adapter(name: str, request: Request) -> dict[str, object]:
    ctx = _ctx(request)
    try:
        return await ctx.sources.start(name, real_allowed=ctx.sources.real_source_active)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="未知适配器") from exc


@router.post("/api/adapters/{name}/stop")
async def stop_adapter(name: str, request: Request) -> dict[str, object]:
    ctx = _ctx(request)
    try:
        return await ctx.sources.stop(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="未知适配器") from exc


@router.get("/api/adapters/{name}/health")
async def adapter_health(name: str, request: Request) -> dict[str, object]:
    ctx = _ctx(request)
    try:
        return ctx.sources.health(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="未知适配器") from exc


@router.get("/api/adapters/{name}/metrics")
async def adapter_metrics(name: str, request: Request) -> dict[str, object]:
    ctx = _ctx(request)
    try:
        return ctx.sources.metrics(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="未知适配器") from exc


@router.post("/api/adapters/{name}/reconnect")
async def reconnect_adapter(name: str, request: Request) -> dict[str, object]:
    ctx = _ctx(request)
    try:
        return await ctx.sources.reconnect(
            name,
            now=ctx.clock.time(),
            real_allowed=ctx.sources.real_source_active,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="未知适配器") from exc


@router.post("/api/adapters/{name}/heartbeat")
async def heartbeat_adapter(name: str, request: Request) -> dict[str, object]:
    ctx = _ctx(request)
    try:
        return ctx.sources.heartbeat(name, ctx.clock.time())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="未知适配器") from exc


@router.get("/api/raw-payloads")
async def list_raw(request: Request) -> list[dict[str, object]]:
    return _ctx(request).store.list_raw()


@router.post("/api/raw-payloads")
async def create_raw(body: RawIn, request: Request) -> dict[str, object]:
    if body.adapter not in {"sim", "mock"}:
        raise HTTPException(status_code=400, detail="只加密保存本地模拟原文")
    return _ctx(request).save_encrypted_raw(body.adapter, body.payload)


@router.delete("/api/raw-payloads")
async def delete_raw_all(request: Request) -> dict[str, object]:
    deleted = _ctx(request).store.delete_raw()
    return {"deleted": deleted}


@router.delete("/api/raw-payloads/{raw_id}")
async def delete_raw_one(raw_id: str, request: Request) -> dict[str, object]:
    deleted = _ctx(request).store.delete_raw(raw_id)
    if deleted == 0:
        raise HTTPException(status_code=404, detail="找不到原文")
    return {"deleted": deleted}


@router.get("/api/overlay/config")
async def overlay_config(request: Request) -> dict[str, object]:
    return _ctx(request).overlay_public_config()


@router.post("/api/overlay/control")
async def overlay_control(body: OverlayControlIn, request: Request) -> dict[str, object]:
    return _ctx(request).update_overlay_control(mute=body.mute, seek=body.seek, clear_seek=body.clear_seek)


@router.get("/api/overlay/stats")
async def overlay_stats(request: Request) -> dict[str, object]:
    ctx = _ctx(request)
    stats = dict(ctx.overlay_stats)
    stats["heap_samples"] = list(ctx.overlay_heap)
    return stats


@router.post("/api/overlay/stats")
async def post_overlay_stats(body: OverlayStatsIn, request: Request) -> dict[str, object]:
    return _ctx(request).record_overlay_stats(body.model_dump())


@router.post("/api/debug/emotion")
async def debug_emotion(body: EmotionSliderIn, request: Request) -> dict[str, object]:
    return _ctx(request).emotion.force_emotion(body.emotion, body.intensity)


@router.post("/api/debug/step")
async def debug_step(request: Request) -> dict[str, object]:
    """单步触发一条模拟点赞，方便调试台逐帧看效果。"""

    ctx = _ctx(request)
    stamp = int(ctx.clock.time() * 1000)
    return await ctx.ingest(
        {
            "adapter": "sim",
            "source_msg_id": f"step-{stamp}",
            "type": "like",
            "user_id": f"step-{stamp}",
            "nickname": "单步",
        }
    )


@router.get("/api/audit")
async def audit(request: Request, limit: int = 50) -> list[dict[str, object]]:
    return _ctx(request).store.list_audit(limit)
