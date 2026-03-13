"""Orchestrator plugin -- research workflow coordination."""
from __future__ import annotations

from typing import Any

from open_researcher.kernel.plugin import PluginBase


class OrchestratorPlugin(PluginBase):
    """Coordinates the Scout -> Manager -> Critic -> Experiment research cycle.

    Wraps the existing ResearchLoop and adapts it to emit events through
    the kernel's EventBus instead of raw callbacks.
    """

    name = "orchestrator"
    dependencies = ["storage"]

    def __init__(self) -> None:
        self._kernel: Any = None
        self._loop: Any = None

    async def start(self, kernel: Any) -> None:
        self._kernel = kernel

    async def stop(self) -> None:
        self._kernel = None
        self._loop = None

    @property
    def kernel(self) -> Any:
        if self._kernel is None:
            raise RuntimeError("OrchestratorPlugin not started")
        return self._kernel
