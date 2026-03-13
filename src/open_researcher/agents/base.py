"""Abstract base class for AI agent adapters."""

import os
import shutil
import signal
import subprocess
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable

from open_researcher.token_tracking import TokenMetrics


class AgentAdapter(ABC):
    """Base class that all agent adapters must implement."""

    name: str
    command: str

    def __init__(self, config: dict | None = None):
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._config = config or {}
        self.last_token_metrics: TokenMetrics | None = None

    def check_installed(self) -> bool:
        """Return True if the agent binary is available on PATH."""
        return shutil.which(self.command) is not None

    def _try_parse_token_line(self, line: str) -> TokenMetrics | None:
        """Parse token usage from an output line. Override in subclasses."""
        return None

    @abstractmethod
    def build_command(self, program_md: Path, workdir: Path) -> list[str]:
        """Build the subprocess command list to launch the agent."""

    @abstractmethod
    def run(
        self,
        workdir: Path,
        on_output: Callable[[str], None] | None = None,
        program_file: str = "program.md",
        env: dict[str, str] | None = None,
    ) -> int:
        """Launch the agent, stream output via callback, return exit code."""

    def _run_process(
        self,
        cmd: list[str],
        workdir: Path,
        on_output: Callable[[str], None] | None = None,
        stdin_text: str | None = None,
        env: dict[str, str] | None = None,
    ) -> int:
        """Common subprocess execution with streaming output."""
        run_env = None
        if env:
            run_env = {**os.environ, **env}
        proc = subprocess.Popen(
            cmd,
            cwd=str(workdir),
            stdin=subprocess.PIPE if stdin_text else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
            env=run_env,
        )
        if stdin_text:
            try:
                proc.stdin.write(stdin_text)
            except BrokenPipeError:
                pass
            finally:
                try:
                    proc.stdin.close()
                except OSError:
                    pass
        with self._lock:
            self._proc = proc
        try:
            self.last_token_metrics = None
            _metrics = TokenMetrics()
            for line in proc.stdout:
                parsed = self._try_parse_token_line(line)
                if parsed:
                    _metrics = parsed
                if on_output:
                    on_output(line.rstrip("\n"))
            if _metrics.tokens_total > 0:
                self.last_token_metrics = _metrics
        finally:
            if proc.stdout:
                proc.stdout.close()
            proc.wait()
        return proc.returncode

    def terminate(self) -> None:
        """Terminate the running agent subprocess."""
        with self._lock:
            proc = self._proc
        if proc and proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    pass
