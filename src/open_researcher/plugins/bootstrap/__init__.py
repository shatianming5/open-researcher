"""Bootstrap plugin — repository detection and environment preparation."""
from __future__ import annotations

from typing import Any

from open_researcher.kernel.plugin import PluginBase


class BootstrapPlugin(PluginBase):
    """Handles repository detection, environment setup, and preparation commands.

    Listens for ``run.requested`` events and emits ``bootstrap.*`` events
    during the preparation phase.
    """

    name = "bootstrap"
    dependencies = ["storage"]

    def __init__(self) -> None:
        self._kernel: Any = None

    async def start(self, kernel: Any) -> None:
        self._kernel = kernel

    async def stop(self) -> None:
        self._kernel = None

    @property
    def kernel(self) -> Any:
        if self._kernel is None:
            raise RuntimeError("BootstrapPlugin not started")
        return self._kernel
