"""关键告警写进同一条审计。"""

from __future__ import annotations

from typing import Any

from src.audit.log import AuditLog


def raise_alert(audit: AuditLog, kind: str, detail: dict[str, Any]) -> dict[str, Any]:
    safe = {key: value for key, value in detail.items() if key != "blob"}
    return audit.record(f"alert_{kind}", safe)


def adapter_problem(health: dict[str, Any]) -> str | None:
    """官方桩保持降级是预期，不告警。模拟源只有在跑起来之后掉线才告警。"""

    name = str(health.get("name") or "")
    if name == "official":
        return None
    state = str(health.get("state") or "")
    if state in {"", "healthy", "disabled"}:
        return None
    return f"{name}:{state}"
