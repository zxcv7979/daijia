"""适配器注册表。模拟源随时可用；官方桩默认可查询，但不会推送事件。"""

from __future__ import annotations

from typing import Any

from src.adapters.governance import IngressGovernor, ReconnectBackoff
from src.adapters.mock_source import MockSource
from src.adapters.official import OfficialAdapterStub
from src.settings import Settings


class AdapterRegistry:
    def __init__(self, settings: Settings) -> None:
        gov = settings.default_model.adapters.governance
        self.mock = MockSource()
        self.official = OfficialAdapterStub()
        self.governor = IngressGovernor(
            queue_max=gov.queue_max,
            dedup_window_sec=float(gov.dedup_window_sec),
            heartbeat_timeout_sec=gov.heartbeat_timeout_sec,
            backoff=ReconnectBackoff(
                base_sec=gov.backoff_base_sec,
                factor=gov.backoff_factor,
                cap_sec=gov.backoff_cap_sec,
                stable_after_sec=gov.stable_after_sec,
            ),
        )
        self._real_confirmed = False

    @property
    def real_source_active(self) -> bool:
        return self._real_confirmed

    def confirm_real_source(self) -> None:
        self._real_confirmed = True

    def revoke_real_source(self) -> None:
        self._real_confirmed = False

    def describe(self) -> list[dict[str, Any]]:
        return [self.mock.health() | {"metrics": self.mock.metrics()}, self.official.health() | {"metrics": self.official.metrics()}]

    async def start(self, name: str, *, real_allowed: bool) -> dict[str, object]:
        if name == "mock":
            return await self.mock.start()
        if name == "official":
            if not real_allowed or not self._real_confirmed:
                return {
                    "started": False,
                    "adapter": "official",
                    "state": "disabled",
                    "reason": "真实源未经过二次确认",
                }
            # 确认之后也只做健康检查和降级，不推送平台数据。
            return await self.official.start()
        raise KeyError(name)

    async def stop(self, name: str) -> dict[str, object]:
        adapter = self._require(name)
        return await adapter.stop()

    def health(self, name: str) -> dict[str, object]:
        return self._require(name).health()

    def metrics(self, name: str) -> dict[str, object]:
        base = self._require(name).metrics()
        if name == "mock":
            base["governor"] = self.governor.snapshot()
        return base

    async def reconnect(self, name: str, *, now: float, real_allowed: bool) -> dict[str, object]:
        delay = self.governor.backoff.next_delay(now)
        self.governor.last_reconnect_delay = delay
        if name == "official" and (not real_allowed or not self._real_confirmed):
            result = await self.official.reconnect()
            result["delay_sec"] = delay
            return result
        adapter = self._require(name)
        result = await adapter.reconnect()
        result["delay_sec"] = delay
        if name == "mock" and result.get("reconnected"):
            self.mock.beat(now)
            self.governor.backoff.on_connected(now)
        return result

    def heartbeat(self, name: str, now: float) -> dict[str, object]:
        if name != "mock":
            return self.official.health()
        self.mock.beat(now)
        self.governor.backoff.on_connected(now)
        self.governor.backoff.note_stable(now)
        return self.mock.health()

    def check_liveness(self, now: float) -> dict[str, object] | None:
        """心跳超时则标记不健康。调用方再用 reconnect 做退避。"""

        if not self.mock.running:
            return None
        if self.mock.alive(now, self.governor.heartbeat_timeout_sec):
            self.governor.backoff.note_stable(now)
            return None
        self.mock.mark_unhealthy()
        return {"adapter": "mock", "state": "unhealthy"}

    def _require(self, name: str) -> Any:
        if name == "mock":
            return self.mock
        if name == "official":
            return self.official
        raise KeyError(name)
