"""Kernel -- the microkernel that ties EventBus, EventStore, and Registry."""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

from open_researcher.kernel.bus import EventBus
from open_researcher.kernel.plugin import PluginProtocol, Registry
from open_researcher.kernel.store import EventStore


class Kernel:
    def __init__(self, *, db_path: str | Path = ":memory:") -> None:
        self.store = EventStore(db_path)
        self.bus = EventBus(self.store)
        self._registry = Registry()

    async def boot(self, plugins: Sequence[PluginProtocol]) -> None:
        await self.store.open()
        for p in plugins:
            self._registry.register(p)
        for p in self._registry.boot_order():
            await p.start(self)

    async def shutdown(self) -> None:
        for p in reversed(self._registry.boot_order()):
            await p.stop()
        await self.store.close()

    def get_plugin(self, name: str) -> PluginProtocol:
        return self._registry.get(name)
