"""SQLite-backed event store for the microkernel."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from open_researcher.kernel.event import Event

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

    async def open(self) -> None:
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)

    async def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    async def append(self, event: Event) -> None:
        assert self._conn is not None, "Store not opened"
        with self._lock:
            self._conn.execute(
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
            self._conn.commit()

    async def replay(
        self,
        *,
        type_prefix: str = "",
        since: float = 0.0,
    ) -> list[Event]:
        assert self._conn is not None, "Store not opened"
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
            rows = self._conn.execute(
                f"SELECT type, payload, ts, source, corr_id FROM events{where} ORDER BY id",
                params,
            ).fetchall()
        return [
            Event(
                type=r[0],
                payload=json.loads(r[1]),
                ts=r[2],
                source=r[3],
                correlation_id=r[4],
            )
            for r in rows
        ]

    async def count(self) -> int:
        assert self._conn is not None, "Store not opened"
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM events").fetchone()
        return row[0] if row else 0
