"""本地模拟源。不连接任何平台，用来验证治理层和压测。"""

from __future__ import annotations


class MockSource:
    name = "mock"
    kind = "sim"

    def __init__(self) -> None:
        self.running = False
        self.state = "disabled"
        self.reconnects = 0
        self.heartbeats = 0
        self._last_heartbeat: float | None = None

    async def start(self) -> dict[str, object]:
        self.running = True
        self.state = "healthy"
        return {"started": True, "adapter": self.name, "state": self.state}

    async def stop(self) -> dict[str, object]:
        self.running = False
        self.state = "disabled"
        return {"stopped": True, "adapter": self.name}

    def beat(self, now: float) -> None:
        self._last_heartbeat = now
        self.heartbeats += 1
        if self.running:
            self.state = "healthy"

    def alive(self, now: float, timeout_sec: float) -> bool:
        if not self.running or self._last_heartbeat is None:
            return False
        return now - self._last_heartbeat <= timeout_sec

    def health(self) -> dict[str, object]:
        return {
            "name": self.name,
            "kind": self.kind,
            "state": self.state,
            "alive": self.state == "healthy",
            "reconnects": self.reconnects,
        }

    def metrics(self) -> dict[str, object]:
        return {"reconnects": self.reconnects, "heartbeats": self.heartbeats, "state": self.state}

    async def reconnect(self) -> dict[str, object]:
        self.reconnects += 1
        self.running = True
        self.state = "healthy"
        return {"reconnected": True, "adapter": self.name, "state": self.state}

    def mark_unhealthy(self) -> None:
        self.state = "unhealthy"
        self.running = False
