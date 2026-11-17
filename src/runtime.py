"""把配置、总线、规范化和演示服务接到同一个上下文。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from pathlib import Path

from pydantic import ValidationError

from src.adapters.crypto import decrypt, derive_key, encrypt
from src.adapters.registry import AdapterRegistry
from src.adapters.sim_replay import SimReplay
from src.audit.log import AuditLog
from src.bus.event_bus import EventBus
from src.bus.metrics import LatencyStats
from src.clock import SystemClock
from src.emotion.engine import EmotionEngine
from src.mapping.table import MappingTable
from src.models import NormOp, RawIncoming, public_event
from src.normalize.pipeline import Normalizer
from src.print_show.jobs import PrintShow
from src.settings import Settings
from src.store import Store

logger = logging.getLogger("live_show")


class Context:
    def __init__(self, root: Path, clock: SystemClock | None = None) -> None:
        self.root = root
        self.clock = clock or SystemClock()
        self.settings = Settings(root)
        self.store = Store(root / "data" / "live_show.db")
        self.audit = AuditLog(self.settings.audit_path(), self.store)
        self.stats = LatencyStats()
        self.bus = EventBus(buffer_sec=self.settings.default_model.bus.reconnect_buffer_sec, clock=self.clock)
        self.normalizer = Normalizer(self.settings)
        self.mapping = MappingTable(self.settings)
        self.emotion = EmotionEngine(self.settings, self.bus, self.mapping, self.clock)
        self.printer = PrintShow(self.settings, self.bus, self.store, self.emotion, self.clock)
        self.replay = SimReplay(self.settings)
        self.replay.ingest_cb = self.ingest
        self.sources = AdapterRegistry(self.settings)
        self.official = self.sources.official
        self._tasks: list[asyncio.Task[None]] = []
        self._collection_was_on = False
        self._real_source_warned = False
        self._started = False

    async def startup(self) -> None:
        if self.settings.collection_enabled():
            # 进程启动时如果文件里已经打开采集，也要留审计。不会因此连接平台。
            self.audit.record_collection_enabled(source="startup", previous=False)
        self._collection_was_on = self.settings.collection_enabled()
        if self.settings.real_source_configured() and not self.sources.real_source_active:
            self.audit.record(
                "real_source_ignored",
                {
                    "configured": True,
                    "active": False,
                    "note": "配置写成了 true，但本进程没有二次确认，真实源保持关闭。",
                },
            )
            self._real_source_warned = True
        self._tasks = [
            asyncio.create_task(self._watch_config(), name="config-watch"),
            asyncio.create_task(self._broadcast_emotion(), name="emotion-broadcast"),
            asyncio.create_task(self._tick_prints(), name="print-tick"),
        ]
        self._started = True
        logger.info(
            "演示服务已就绪 collection_enabled=%s official=disabled",
            self.settings.collection_enabled(),
        )

    async def shutdown(self) -> None:
        await self.replay.stop()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        self.close()

    def close(self) -> None:
        try:
            self.store.close()
        except Exception:
            logger.exception("关闭数据库失败")

    async def ingest(self, payload: dict) -> dict[str, object]:
        """模拟事件入口。合法事件不会因为忙而丢弃。"""

        started = time.perf_counter()
        try:
            raw = RawIncoming.model_validate(payload)
        except ValidationError:
            self.stats.rejected += 1
            return {"ok": False, "reason": "rejected"}
        if raw.adapter not in {"sim", "mock"}:
            self.stats.rejected += 1
            return {"ok": False, "reason": "未确认的来源不能进入管道"}
        if raw.ts is None:
            raw.ts = self.clock.time()
        self.stats.received += 1
        try:
            result = self.normalizer.feed(raw)
        except Exception:
            self.stats.dropped += 1
            logger.exception("规范化失败")
            return {"ok": False, "reason": "dropped"}
        if result.op == NormOp.duplicate or result.event is None:
            self.stats.duplicates += 1
            self.stats.observe((time.perf_counter() - started) * 1000)
            return {"ok": True, "op": "duplicate", "event_id": None}
        public = public_event(result.event)
        try:
            self.store.save_event(public)
            self.store.save_ingress(result.source_key, result.event.event_id, result.op.value, result.event.ts)
            self.bus.publish("event", {"op": result.op.value, "event": public})
        except Exception:
            self.stats.dropped += 1
            logger.exception("事件发布失败")
            return {"ok": False, "reason": "dropped"}
        self.stats.published += 1
        if result.op == NormOp.update:
            self.stats.updates += 1
        try:
            resolution = self.emotion.handle(result.event, highlight=raw.highlight, op=result.op.value)
            self.printer.maybe_autoprint(result.event, resolution)
        except Exception:
            # 事件已经进入总线，下游失败单独记日志，不算丢事件。
            logger.exception("情绪或打印下游失败")
        self.stats.observe((time.perf_counter() - started) * 1000)
        return {"ok": True, "op": result.op.value, "event_id": result.event.event_id}

    async def set_collection_enabled(self, enabled: bool) -> dict[str, object]:
        previous = self.settings.update_collection_enabled(enabled)
        audited = False
        if enabled and not previous:
            self.audit.record_collection_enabled(source="api", previous=previous)
            audited = True
        self._collection_was_on = self.settings.collection_enabled()
        official = await self.official.start() if enabled else {"started": False, "adapter": "official", "reason": "采集关闭"}
        return {
            "collection_enabled": self.settings.collection_enabled(),
            "previous": previous,
            "audited": audited,
            "official_adapter": official,
        }

    def real_source_blocked_by_env(self) -> bool:
        raw = os.environ.get("REAL_SOURCE")
        if raw is None or raw.strip() == "":
            return False
        return raw.strip().lower() in {"0", "false", "off", "no"}

    async def set_real_source(self, enabled: bool, confirm: bool) -> dict[str, object]:
        """二次确认之后才把真实源标成可用。官方适配器仍然不推送。"""

        if enabled and not confirm:
            return {
                "ok": False,
                "status": 400,
                "real_source_active": self.sources.real_source_active,
                "detail": "需要二次确认。未写入审计，真实源保持关闭。",
            }
        if enabled and self.real_source_blocked_by_env():
            return {
                "ok": False,
                "status": 409,
                "real_source_active": False,
                "detail": "环境变量 REAL_SOURCE 明确关闭，拒绝开启。",
            }
        previous_active = self.sources.real_source_active
        if enabled:
            self.settings.update_real_source(True)
            self.sources.confirm_real_source()
            audited = not previous_active
            if audited:
                self.audit.record(
                    "real_source_enabled",
                    {
                        "enabled": True,
                        "confirm": True,
                        "official_adapter": "stub",
                        "note": "二次确认后仅允许注册和健康检查。官方适配器仍是桩，没有平台 I/O。",
                    },
                )
            official = await self.sources.start("official", real_allowed=True)
        else:
            self.settings.update_real_source(False)
            self.sources.revoke_real_source()
            official = await self.sources.official.stop()
            audited = False
        return {
            "ok": True,
            "status": 200,
            "real_source_active": self.sources.real_source_active,
            "real_source_configured": self.settings.real_source_configured(),
            "previous_active": previous_active,
            "audited": audited,
            "official_adapter": official,
        }

    def compliance_view(self) -> dict[str, object]:
        return {
            "collection_enabled": self.settings.collection_enabled(),
            "real_source_active": self.sources.real_source_active,
            "real_source_configured": self.settings.real_source_configured(),
            "real_source_env_blocked": self.real_source_blocked_by_env(),
            "official_adapter": "disabled",
            "note": "真实源默认关闭。二次确认后也只注册桩适配器，不连接平台。",
        }

    def save_encrypted_raw(self, adapter: str, payload: dict[str, object]) -> dict[str, object]:
        token = encrypt(derive_key(self.settings.salt), json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        raw_id = uuid.uuid4().hex
        self.store.save_raw(raw_id, adapter, self.clock.time(), token)
        return {"id": raw_id, "size": len(token)}

    def read_encrypted_raw(self, raw_id: str) -> bytes | None:
        blob = self.store.get_raw_blob(raw_id)
        if blob is None:
            return None
        return decrypt(derive_key(self.settings.salt), blob)

    async def _watch_config(self) -> None:
        while True:
            try:
                changed = self.settings.poll_once()
                enabled = self.settings.collection_enabled()
                if "default.yaml" in changed and enabled and not self._collection_was_on:
                    self.audit.record_collection_enabled(source="config_file", previous=False)
                self._collection_was_on = enabled
                if "default.yaml" in changed and not self.settings.real_source_configured():
                    self.sources.revoke_real_source()
                    self._real_source_warned = False
                if (
                    self.settings.real_source_configured()
                    and not self.sources.real_source_active
                    and not self._real_source_warned
                ):
                    self.audit.record(
                        "real_source_ignored",
                        {
                            "configured": True,
                            "active": False,
                            "note": "配置写成了 true，但没有二次确认，真实源保持关闭。",
                        },
                    )
                    self._real_source_warned = True
            except Exception:
                logger.exception("配置轮询失败")
            await asyncio.sleep(0.4)

    async def _broadcast_emotion(self) -> None:
        last: tuple | None = None
        while True:
            try:
                payload = self.emotion.snapshot()
                key = (
                    payload.get("emotion"),
                    round(float(payload.get("intensity") or 0), 2),
                    payload.get("priority"),
                    payload.get("is_ducking"),
                    payload.get("source_event"),
                    payload.get("phase"),
                )
                if key != last:
                    self.bus.publish("emotion", payload)
                    last = key
            except Exception:
                logger.exception("情绪广播失败")
            await asyncio.sleep(0.1)

    async def _tick_prints(self) -> None:
        while True:
            try:
                self.printer.tick()
            except Exception:
                logger.exception("虚拟打印推进失败")
            await asyncio.sleep(0.1)


def build_context(root: Path, clock: SystemClock | None = None) -> Context:
    return Context(root, clock=clock)
