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

    def close(self) -> None:
        with self._lock:
            self._conn.close()
