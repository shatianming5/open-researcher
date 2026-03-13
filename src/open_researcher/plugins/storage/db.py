"""Thin async wrapper around a SQLite connection with auto-migration."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from open_researcher.plugins.storage.migrations import apply_migrations


class Database:
    """Manages a single SQLite connection with WAL mode and migrations."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self.conn: sqlite3.Connection | None = None
        self.lock = threading.Lock()

    async def open(self) -> None:
        with self.lock:
            if self.conn is not None:
                return
            self.conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            apply_migrations(self.conn)

    async def close(self) -> None:
        with self.lock:
            if self.conn:
                self.conn.close()
                self.conn = None
