"""Bootstrap preparation — command execution and state tracking."""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BootstrapState:
    """Tracks the state of the bootstrap process."""
    started_at: float = 0.0
    completed_at: float = 0.0
    steps_completed: list[str] = field(default_factory=list)
    steps_failed: list[str] = field(default_factory=list)
    is_ready: bool = False

    def mark_started(self) -> None:
        self.started_at = time.time()

    def mark_step_completed(self, step: str) -> None:
        self.steps_completed.append(step)

    def mark_step_failed(self, step: str) -> None:
        self.steps_failed.append(step)

    def mark_ready(self) -> None:
        self.completed_at = time.time()
        self.is_ready = True


def run_preparation_command(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: int = 300,
) -> tuple[bool, str]:
    """Run a bootstrap preparation command.

    Returns (success, output) tuple.
    """
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        output = result.stdout + result.stderr
        return result.returncode == 0, output.strip()
    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {timeout}s"
    except FileNotFoundError:
        return False, f"Command not found: {command[0]}"
