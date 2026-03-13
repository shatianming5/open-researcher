"""Schema migration engine for the state database."""
from __future__ import annotations

import sqlite3

from open_researcher.plugins.storage.models import SCHEMA_V1

CURRENT_VERSION = 1
_MIGRATIONS: list[tuple[int, str]] = [(1, SCHEMA_V1)]


def apply_migrations(conn: sqlite3.Connection) -> None:
    """Apply all pending migrations up to CURRENT_VERSION."""
    row = conn.execute("PRAGMA user_version").fetchone()
    current = row[0] if row else 0
    for target, sql in _MIGRATIONS:
        if current < target:
            conn.executescript(sql)
            conn.execute(f"PRAGMA user_version = {target}")
            conn.commit()
            current = target
