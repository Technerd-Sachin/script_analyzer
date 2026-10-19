"""SQLite store for documents, jobs and job events (production would use Postgres behind this interface)."""

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
  doc_id TEXT PRIMARY KEY, filename TEXT, size INTEGER, path TEXT, created_at REAL
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, doc_id TEXT, status TEXT, stage TEXT, progress REAL, error TEXT,
  report_key TEXT, options TEXT, created_at REAL, updated_at REAL
);
CREATE TABLE IF NOT EXISTS events (
  job_id TEXT, seq INTEGER, type TEXT, data TEXT, ts REAL, PRIMARY KEY (job_id, seq)
);
"""


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._lock = threading.Lock()

    def _q(self, sql: str, args: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, args).fetchall())

    def add_document(self, doc_id: str, filename: str, size: int, path: str) -> None:
        self._q(
            "INSERT OR IGNORE INTO documents VALUES (?,?,?,?,?)", (doc_id, filename, size, path, time.time())
        )

    def document(self, doc_id: str) -> dict[str, Any] | None:
        rows = self._q("SELECT * FROM documents WHERE doc_id=?", (doc_id,))
        return dict(rows[0]) if rows else None

    def create_job(self, doc_id: str, options: dict[str, Any]) -> str:
        job_id = uuid.uuid4().hex[:16]
        now = time.time()
        self._q(
            "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)",
            (job_id, doc_id, "queued", "queued", 0.0, None, None, json.dumps(options), now, now),
        )
        return job_id

    def update_job(self, job_id: str, **fields: Any) -> None:
        cols = ", ".join(f"{k}=?" for k in fields)
        self._q(f"UPDATE jobs SET {cols}, updated_at=? WHERE id=?", (*fields.values(), time.time(), job_id))

    def job(self, job_id: str) -> dict[str, Any] | None:
        rows = self._q("SELECT * FROM jobs WHERE id=?", (job_id,))
        return dict(rows[0]) if rows else None

    def jobs_in(self, statuses: tuple[str, ...]) -> list[dict[str, Any]]:
        marks = ",".join("?" * len(statuses))
        return [
            dict(r)
            for r in self._q(f"SELECT * FROM jobs WHERE status IN ({marks}) ORDER BY created_at", statuses)
        ]

    def add_event(self, job_id: str, type_: str, data: dict[str, Any]) -> None:
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(seq), -1) + 1 FROM events WHERE job_id=?", (job_id,)
            ).fetchone()
            self._conn.execute(
                "INSERT INTO events VALUES (?,?,?,?,?)",
                (job_id, row[0], type_, json.dumps(data), time.time()),
            )

    def events_after(self, job_id: str, seq: int) -> list[dict[str, Any]]:
        rows = self._q(
            "SELECT seq, type, data FROM events WHERE job_id=? AND seq>? ORDER BY seq", (job_id, seq)
        )
        return [{"seq": r["seq"], "type": r["type"], "data": json.loads(r["data"])} for r in rows]

    def old_documents(self, before: float) -> list[dict[str, Any]]:
        return [dict(r) for r in self._q("SELECT * FROM documents WHERE created_at < ?", (before,))]

    def delete_document(self, doc_id: str) -> None:
        self._q("DELETE FROM documents WHERE doc_id=?", (doc_id,))
