"""SQLite-backed event store for the microkernel."""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from open_researcher.kernel.event import Event

logger = logging.getLogger(__name__)

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    type      TEXT    NOT NULL,
    payload   TEXT    NOT NULL,
    ts        REAL    NOT NULL,
    source    TEXT    NOT NULL DEFAULT '',
    corr_id   TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
CREATE INDEX IF NOT EXISTS idx_events_ts   ON events(ts);
"""


class EventStore:
    """Append-only event log backed by SQLite."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    def _require_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Store not opened")
        return self._conn

    async def open(self) -> None:
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)

    async def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    async def append(self, event: Event) -> None:
        conn = self._require_conn()
        with self._lock:
            conn.execute(
                "INSERT INTO events (type, payload, ts, source, corr_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    event.type,
                    json.dumps(event.payload),
                    event.ts,
                    event.source,
                    event.correlation_id,
                ),
            )
            conn.commit()

    async def replay(
        self,
        *,
        type_prefix: str = "",
        since: float = 0.0,
    ) -> list[Event]:
        conn = self._require_conn()
        clauses: list[str] = []
        params: list[object] = []
        if type_prefix:
            clauses.append("type LIKE ? || '%' ESCAPE '\\'")
            escaped = type_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params.append(escaped)
        if since:
            clauses.append("ts > ?")
            params.append(since)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._lock:
            rows = conn.execute(
                f"SELECT type, payload, ts, source, corr_id FROM events{where} ORDER BY id",
                params,
            ).fetchall()
        events: list[Event] = []
        for r in rows:
            try:
                payload = json.loads(r[1])
            except (json.JSONDecodeError, TypeError):
                logger.warning("Skipping event with invalid JSON payload: id type=%s", r[0])
                continue
            events.append(Event(
                type=r[0],
                payload=payload,
                ts=r[2],
                source=r[3],
                correlation_id=r[4],
            ))
        return events

    async def count(self) -> int:
        conn = self._require_conn()
        with self._lock:
            row = conn.execute("SELECT COUNT(*) FROM events").fetchone()
        return row[0] if row else 0
