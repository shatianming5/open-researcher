"""SQLite-backed idea pool with atomic claim semantics."""
from __future__ import annotations

import time
from typing import Any

from open_researcher.plugins.storage.db import Database


class IdeaPoolStore:
    """Manages a pool of research ideas stored in the ``ideas`` table.

    Each idea has a priority; ``claim`` atomically selects the highest-priority
    pending idea and marks it as claimed by a worker.
    """

    def __init__(self, db: Database) -> None:
        self._db = db
        self._counter = 0

    @property
    def _conn(self):
        """Return the underlying connection, raising if not open."""
        conn = self._db.conn
        if conn is None:
            raise RuntimeError("Database is not open")
        return conn

    def _next_id(self) -> str:
        self._counter += 1
        return f"idea-{self._counter:03d}"

    async def add(
        self,
        title: str,
        priority: float = 0,
        metadata: str | None = None,
    ) -> dict[str, Any]:
        """Insert a new idea with *pending* status and return it as a dict."""
        idea_id = self._next_id()
        now = time.time()
        self._conn.execute(
            "INSERT INTO ideas (id, title, status, priority, created_at, metadata) "
            "VALUES (?, ?, 'pending', ?, ?, ?)",
            (idea_id, title, priority, now, metadata),
        )
        self._conn.commit()
        return {
            "id": idea_id,
            "title": title,
            "status": "pending",
            "priority": priority,
            "claimed_by": None,
            "created_at": now,
            "metadata": metadata,
        }

    async def get(self, idea_id: str) -> dict[str, Any] | None:
        """Return a single idea by *id*, or ``None``."""
        cur = self._conn.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,))
        row = cur.fetchone()
        if row is None:
            return None
        return self._row_to_dict(cur, row)

    async def list_by_status(self, status: str) -> list[dict[str, Any]]:
        """Return all ideas matching *status*, ordered by priority descending."""
        cur = self._conn.execute(
            "SELECT * FROM ideas WHERE status = ? ORDER BY priority DESC",
            (status,),
        )
        return [self._row_to_dict(cur, row) for row in cur.fetchall()]

    async def claim(self, worker_id: str) -> dict[str, Any] | None:
        """Atomically claim the highest-priority pending idea.

        Returns the claimed idea dict, or ``None`` if no pending ideas exist.
        """
        cur = self._conn.execute(
            "UPDATE ideas SET status = 'claimed', claimed_by = ? "
            "WHERE id = ("
            "  SELECT id FROM ideas WHERE status = 'pending' "
            "  ORDER BY priority DESC LIMIT 1"
            ") RETURNING *",
            (worker_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        self._conn.commit()
        return self._row_to_dict(cur, row)

    async def complete(self, idea_id: str) -> dict[str, Any] | None:
        """Mark an idea as *done*."""
        cur = self._conn.execute(
            "UPDATE ideas SET status = 'done' WHERE id = ? RETURNING *",
            (idea_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        self._conn.commit()
        return self._row_to_dict(cur, row)

    async def skip(self, idea_id: str) -> dict[str, Any] | None:
        """Mark an idea as *skipped*."""
        cur = self._conn.execute(
            "UPDATE ideas SET status = 'skipped' WHERE id = ? RETURNING *",
            (idea_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        self._conn.commit()
        return self._row_to_dict(cur, row)

    @staticmethod
    def _row_to_dict(cursor, row) -> dict[str, Any]:
        """Convert a sqlite3 Row (tuple) to a dict using cursor.description."""
        cols = [desc[0] for desc in cursor.description]
        return dict(zip(cols, row))
