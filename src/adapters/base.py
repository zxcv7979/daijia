"""采集适配器接口。实现只负责生命周期和健康，不负责平台报文。"""

from __future__ import annotations

from typing import Protocol


class SourceAdapter(Protocol):
    name: str
    kind: str

    async def start(self) -> dict[str, object]:
        """开始推送。真实适配器在未确认时必须拒绝。"""

    async def stop(self) -> dict[str, object]:
        """停止推送。"""

    def health(self) -> dict[str, object]:
        """返回 disabled / healthy / degraded / unhealthy。"""

    def metrics(self) -> dict[str, object]:
        """计数器。不要包含原文或 PII。"""

    async def reconnect(self) -> dict[str, object]:
        """按治理层给出的退避后重连。官方桩不得发起网络请求。"""
