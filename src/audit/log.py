"""追加写审计日志。打开真实采集时必须留下一条记录。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from src.store import Store


class AuditLog:
    def __init__(self, path: Path, store: Store) -> None:
        self.path = path
        self.store = store
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, action: str, detail: dict[str, Any]) -> dict[str, Any]:
        row = {"ts": time.time(), "action": action, "detail": detail}
        line = json.dumps(row, ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        self.store.save_audit(row["ts"], action, detail)
        return row

    def record_collection_enabled(self, *, source: str, previous: bool) -> dict[str, Any]:
        return self.record(
            "collection_enabled",
            {
                "enabled": True,
                "previous": previous,
                "source": source,
                "official_adapter": "disabled",
                "note": "仅记录审计。P1 不连接任何平台，官方适配器保持禁用桩。",
            },
        )
