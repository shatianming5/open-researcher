"""CLI plugin -- Typer-based command-line interface."""
from __future__ import annotations

from typing import Any

from open_researcher.kernel.plugin import PluginBase


class CLIPlugin(PluginBase):
    """Manages the command-line interface using Typer.

    Provides commands that trigger workflows via kernel.bus.emit().
    """

    name = "cli"
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
            raise RuntimeError("CLIPlugin not started")
        return self._kernel
