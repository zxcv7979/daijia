"""官方平台适配器桩。

P1 不采集任何真实直播间。这里没有登录、签名、Cookie、反爬或平台地址。
即使 live.collection_enabled 被打开，start() 也只会说明自己没有启动。
"""

from __future__ import annotations


class OfficialAdapterStub:
    name = "official"
    enabled = False

    def __init__(self) -> None:
        self.start_calls = 0

    async def start(self) -> dict[str, object]:
        self.start_calls += 1
        return {
            "started": False,
            "adapter": self.name,
            "reason": "P1 禁用官方采集适配器，未实现任何平台接入",
        }
