"""Execution plugin -- worker lifecycle, GPU management, worktree isolation."""
from __future__ import annotations

from typing import Any

from open_researcher.kernel.plugin import PluginBase


class ExecutionPlugin(PluginBase):
    """Manages experiment execution: workers, GPU allocation, worktrees."""

    name = "execution"
    dependencies = ["storage"]

    def __init__(self) -> None:
        self._kernel: Any = None
        self._gpu_manager: Any = None

    async def start(self, kernel: Any) -> None:
        self._kernel = kernel

    async def stop(self) -> None:
        self._kernel = None
        self._gpu_manager = None

    @property
    def kernel(self) -> Any:
        if self._kernel is None:
            raise RuntimeError("ExecutionPlugin not started")
        return self._kernel
