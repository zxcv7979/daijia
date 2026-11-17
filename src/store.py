"""演示用 SQLite。只保存已经脱敏的公开字段。"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init()

    def _init(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    ts REAL NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ingress (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_key TEXT,
                    event_id TEXT,
                    op TEXT NOT NULL,
                    ts REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS print_jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    progress REAL NOT NULL,
                    payload TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    action TEXT NOT NULL,
                    detail TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS raw_payloads (
                    id TEXT PRIMARY KEY,
                    adapter TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    blob TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS avatars (
                    avatar_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    preset_id TEXT,
                    job_id TEXT,
                    name TEXT,
                    glb_rel TEXT,
                    approved INTEGER NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS avatar_jobs (
                    job_id TEXT PRIMARY KEY,
                    avatar_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS avatar_photos (
                    photo_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    blob TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    retain_until REAL NOT NULL
                );
                """
            )
            self._conn.commit()

    def save_event(self, event: dict[str, Any]) -> None:
        payload = json.dumps(event, ensure_ascii=False)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO events (event_id, type, ts, payload)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    type = excluded.type,
                    ts = excluded.ts,
                    payload = excluded.payload
                """,
                (event["event_id"], event["type"], float(event["ts"]), payload),
            )
            self._conn.commit()

    def save_ingress(self, source_key: str, event_id: str, op: str, ts: float) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO ingress (source_key, event_id, op, ts) VALUES (?, ?, ?, ?)",
                (source_key, event_id, op, ts),
            )
            self._conn.commit()

    def count_events(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()
        return int(row["n"])

    def count_ingress(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM ingress").fetchone()
        return int(row["n"])

    def list_events(self, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload FROM events ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def save_job(self, job: dict[str, Any]) -> None:
        payload = json.dumps(job, ensure_ascii=False)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO print_jobs (job_id, status, progress, payload, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    status = excluded.status,
                    progress = excluded.progress,
                    payload = excluded.payload
                """,
                (job["job_id"], job["status"], float(job["progress"]), payload, float(job["created_at"])),
            )
            self._conn.commit()

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload FROM print_jobs ORDER BY created_at DESC"
            ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload FROM print_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["payload"])

    def save_audit(self, ts: float, action: str, detail: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO audit (ts, action, detail) VALUES (?, ?, ?)",
                (ts, action, json.dumps(detail, ensure_ascii=False)),
            )
            self._conn.commit()

    def list_audit(self, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 200))
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, action, detail FROM audit ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        result = []
        for row in rows:
            result.append(
                {"ts": row["ts"], "action": row["action"], "detail": json.loads(row["detail"])}
            )
        return result

    def save_raw(self, raw_id: str, adapter: str, created_at: float, blob: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO raw_payloads (id, adapter, created_at, blob) VALUES (?, ?, ?, ?)",
                (raw_id, adapter, created_at, blob),
            )
            self._conn.commit()

    def list_raw(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, adapter, created_at, length(blob) AS size FROM raw_payloads ORDER BY created_at DESC"
            ).fetchall()
        return [
            {"id": row["id"], "adapter": row["adapter"], "created_at": row["created_at"], "size": row["size"]}
            for row in rows
        ]

    def get_raw_blob(self, raw_id: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT blob FROM raw_payloads WHERE id = ?", (raw_id,)).fetchone()
        if row is None:
            return None
        return str(row["blob"])

    def count_raw(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM raw_payloads").fetchone()
        return int(row["n"])

    def delete_raw(self, raw_id: str | None = None) -> int:
        with self._lock:
            if raw_id is None:
                cur = self._conn.execute("DELETE FROM raw_payloads")
            else:
                cur = self._conn.execute("DELETE FROM raw_payloads WHERE id = ?", (raw_id,))
            self._conn.commit()
            return int(cur.rowcount)

    def save_avatar(self, row: dict) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO avatars (avatar_id, kind, preset_id, job_id, name, glb_rel, approved, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(avatar_id) DO UPDATE SET
                    kind = excluded.kind,
                    preset_id = excluded.preset_id,
                    job_id = excluded.job_id,
                    name = excluded.name,
                    glb_rel = excluded.glb_rel,
                    approved = excluded.approved
                """,
                (
                    row["avatar_id"],
                    row["kind"],
                    row.get("preset_id") or "",
                    row.get("job_id") or "",
                    row.get("name") or row["avatar_id"],
                    row.get("glb_rel") or "",
                    1 if row.get("approved") else 0,
                    float(row["created_at"]),
                ),
            )
            self._conn.commit()

    def list_avatars(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM avatars ORDER BY created_at DESC").fetchall()
        return [dict(row) | {"approved": bool(row["approved"])} for row in rows]

    def get_avatar(self, avatar_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM avatars WHERE avatar_id = ?", (avatar_id,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["approved"] = bool(data["approved"])
        return data

    def set_avatar_approved(self, avatar_id: str, approved: bool) -> None:
        with self._lock:
            self._conn.execute("UPDATE avatars SET approved = ? WHERE avatar_id = ?", (1 if approved else 0, avatar_id))
            self._conn.commit()

    def delete_avatar(self, avatar_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM avatars WHERE avatar_id = ?", (avatar_id,))
            self._conn.commit()

    def save_avatar_job(self, job: dict) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO avatar_jobs (job_id, avatar_id, payload, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET payload = excluded.payload
                """,
                (job["job_id"], job["avatar_id"], json.dumps(job, ensure_ascii=False), float(job["created_at"])),
            )
            self._conn.commit()

    def get_avatar_job(self, job_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT payload FROM avatar_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        return json.loads(row["payload"])

    def jobs_for_avatar(self, avatar_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload FROM avatar_jobs WHERE avatar_id = ? ORDER BY created_at DESC",
                (avatar_id,),
            ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def set_avatar_job_status(self, job_id: str, status: str) -> None:
        job = self.get_avatar_job(job_id)
        if job is None:
            return
        job["status"] = status
        self.save_avatar_job(job)

    def update_avatar_job_result(self, job_id: str, *, status: str, seed: int, glb_rel: str) -> None:
        job = self.get_avatar_job(job_id)
        if job is None:
            return
        job["status"] = status
        job["seed"] = seed
        job["glb_rel"] = glb_rel
        self.save_avatar_job(job)
        avatar = self.get_avatar(job["avatar_id"])
        if avatar:
            avatar["glb_rel"] = glb_rel
            avatar["job_id"] = job_id
            self.save_avatar(avatar)

    def delete_avatar_job(self, job_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM avatar_jobs WHERE job_id = ?", (job_id,))
            self._conn.commit()

    def save_avatar_photo(self, photo_id: str, job_id: str, name: str, blob: str, created_at: float, retain_until: float) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO avatar_photos (photo_id, job_id, name, blob, created_at, retain_until)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (photo_id, job_id, name, blob, created_at, retain_until),
            )
            self._conn.commit()

    def list_avatar_photos(self, job_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT photo_id, job_id, name, blob, created_at, retain_until FROM avatar_photos WHERE job_id = ?",
                (job_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_avatar_photos(self, job_id: str) -> int:
        with self._lock:
            cur = self._conn.execute("DELETE FROM avatar_photos WHERE job_id = ?", (job_id,))
            self._conn.commit()
            return int(cur.rowcount)

    def close(self) -> None:
        with self._lock:
            self._conn.close()
