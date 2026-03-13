"""Kernel -- the microkernel that ties EventBus, EventStore, and Registry."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

from open_researcher.kernel.bus import EventBus
from open_researcher.kernel.plugin import PluginProtocol, Registry
from open_researcher.kernel.store import EventStore

logger = logging.getLogger(__name__)


class Kernel:
    def __init__(self, *, db_path: str | Path = ":memory:") -> None:
        self.store = EventStore(db_path)
        self.bus = EventBus(self.store)
        self._registry = Registry()
        self._started_plugins: list[PluginProtocol] = []

    async def boot(self, plugins: Sequence[PluginProtocol]) -> None:
        await self.store.open()
        for p in plugins:
            self._registry.register(p)
        try:
            for p in self._registry.boot_order():
                await p.start(self)
                self._started_plugins.append(p)
        except Exception:
            logger.exception("Plugin boot failed, shutting down started plugins")
            for p in reversed(self._started_plugins):
                try:
                    await p.stop()
                except Exception:
                    logger.exception("Failed to stop plugin %s during rollback", p.name)
            self._started_plugins.clear()
            await self.store.close()
            raise

    async def shutdown(self) -> None:
        for p in reversed(self._registry.boot_order()):
            try:
                await p.stop()
            except Exception:
                logger.exception("Failed to stop plugin %s", p.name)
        self._started_plugins.clear()
        await self.store.close()

    def get_plugin(self, name: str) -> PluginProtocol:
        return self._registry.get(name)
