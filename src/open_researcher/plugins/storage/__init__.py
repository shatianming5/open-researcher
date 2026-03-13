"""Storage plugin -- SQLite-backed state for Open Researcher."""
from __future__ import annotations

from typing import Any

from open_researcher.kernel.plugin import PluginBase
from open_researcher.plugins.storage.db import Database


class StoragePlugin(PluginBase):
    """Manages the SQLite state database lifecycle."""

    name = "storage"
    dependencies: list[str] = []

    def __init__(self, *, db_path: str = ".research/state.db") -> None:
        self._db_path = db_path
        self.db = Database(db_path)

    async def start(self, kernel: Any) -> None:
        await self.db.open()

    async def stop(self) -> None:
        await self.db.close()
