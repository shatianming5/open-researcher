"""Abstract base class for AI agent adapters."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable


class AgentAdapter(ABC):
    """Base class that all agent adapters must implement."""

    name: str
    command: str

    @abstractmethod
    def check_installed(self) -> bool:
        """Return True if the agent binary is available on PATH."""

    @abstractmethod
    def build_command(self, program_md: Path, workdir: Path) -> list[str]:
        """Build the subprocess command list to launch the agent."""

    @abstractmethod
    def run(
        self,
        workdir: Path,
        on_output: Callable[[str], None] | None = None,
        program_file: str = "program.md",
    ) -> int:
        """Launch the agent, stream output via callback, return exit code."""

    def terminate(self) -> None:
        """Terminate the running agent subprocess. Override in subclasses."""
        pass
