"""按合规配置清理到期照片。不输出照片内容。"""

from __future__ import annotations

from typing import Any

from src.store import Store


def cleanup_expired_photos(store: Store, *, now: float, retention_days: int, dry_run: bool) -> dict[str, Any]:
    """到期日取 retain_until 和 created_at + retention_days 里更早的那个。"""

    due = []
    for row in store.list_photo_retention():
        policy = float(row["created_at"]) + retention_days * 86400
        deadline = min(float(row["retain_until"]), policy)
        if now >= deadline:
            due.append(row["photo_id"])
    deleted = 0 if dry_run else store.delete_photos(due)
    return {
        "dry_run": dry_run,
        "retention_days": retention_days,
        "candidates": len(due),
        "deleted": deleted,
    }
