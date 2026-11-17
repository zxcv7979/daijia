"""官方平台适配器桩。

没有登录、签名、Cookie、反爬或平台地址。
start / reconnect 只报告降级，不发起任何网络请求。
"""

from __future__ import annotations


class OfficialAdapterStub:
    name = "official"
    kind = "official"
    enabled = False

    def __init__(self) -> None:
        self.start_calls = 0
        self.reconnects = 0
        self.state = "disabled"

    async def start(self) -> dict[str, object]:
        self.start_calls += 1
        self.state = "degraded"
        return {
            "started": False,
            "adapter": self.name,
            "state": self.state,
            "reason": "官方适配器是禁用桩，未实现任何平台接入",
        }

    async def stop(self) -> dict[str, object]:
        self.state = "disabled"
        return {"stopped": True, "adapter": self.name, "state": self.state}

    def health(self) -> dict[str, object]:
        return {
            "name": self.name,
            "kind": self.kind,
            "state": self.state,
            "alive": False,
            "degraded": True,
            "detail": "没有平台 I/O。接入前需要用户提供已授权的官方 SDK 或书面接口合同。",
        }

    def metrics(self) -> dict[str, object]:
        return {
            "start_calls": self.start_calls,
            "reconnects": self.reconnects,
            "state": self.state,
            "events_pushed": 0,
        }

    async def reconnect(self) -> dict[str, object]:
        self.reconnects += 1
        self.state = "degraded"
        return {
            "reconnected": False,
            "adapter": self.name,
            "state": self.state,
            "reason": "官方桩不会重连到平台",
        }
