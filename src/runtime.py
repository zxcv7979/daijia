"""把配置、总线、规范化和演示服务接到同一个上下文。"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from pydantic import ValidationError

from src.adapters.official import OfficialAdapterStub
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
        self.official = OfficialAdapterStub()
        self._tasks: list[asyncio.Task[None]] = []
        self._collection_was_on = False
        self._started = False

    async def startup(self) -> None:
        if self.settings.collection_enabled():
            # 进程启动时如果文件里已经打开采集，也要留审计。不会因此连接平台。
            self.audit.record_collection_enabled(source="startup", previous=False)
        self._collection_was_on = self.settings.collection_enabled()
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
        if raw.adapter != "sim":
            self.stats.rejected += 1
            return {"ok": False, "reason": "P1 只接受模拟源"}
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

    async def _watch_config(self) -> None:
        while True:
            try:
                changed = self.settings.poll_once()
                enabled = self.settings.collection_enabled()
                if "default.yaml" in changed and enabled and not self._collection_was_on:
                    self.audit.record_collection_enabled(source="config_file", previous=False)
                self._collection_was_on = enabled
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
