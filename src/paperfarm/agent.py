"""Agent adapter pattern for launching AI agent CLI subprocesses.

Provides a thin wrapper around agent CLIs (Claude Code, Codex, Aider, Gemini)
with a common interface for running them against a research workspace.

Usage::

    agent_adapter = create_agent("claude-code")
    agent = Agent(agent_adapter)
    rc = agent.run(workdir, program_content="...", program_file="program.md")
"""

from __future__ import annotations

import abc
import os
import shutil
import signal
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Base adapter
# ---------------------------------------------------------------------------


class AgentAdapter(abc.ABC):
    """Abstract base for agent CLI adapters."""

    name: str = ""
    command: str = ""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config: dict[str, Any] = config or {}
        self._proc: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()

    def check_installed(self) -> bool:
        """Return True if the agent CLI binary is on PATH."""
        return shutil.which(self.command) is not None

    @abc.abstractmethod
    def run(
        self,
        workdir: Path,
        *,
        on_output: Callable[[str], None] | None = None,
        program_file: str = "program.md",
        env: dict[str, str] | None = None,
    ) -> int:
        """Run the agent in *workdir*. Returns exit code."""

    def terminate(self) -> None:
        """Send SIGTERM to the running agent subprocess (if any)."""
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                self._proc.send_signal(signal.SIGTERM)

    # -- common helper -------------------------------------------------------

    def _run_process(
        self,
        cmd: list[str],
        workdir: Path,
        *,
        on_output: Callable[[str], None] | None = None,
        stdin_text: str | None = None,
        env: dict[str, str] | None = None,
    ) -> int:
        """Spawn *cmd* in *workdir*, stream stdout/stderr, return exit code."""
        merged_env = {**os.environ, **(env or {})}
        # Remove nesting-detection vars so agent CLIs don't refuse to start
        for _var in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
            merged_env.pop(_var, None)
        with self._lock:
            self._proc = subprocess.Popen(
                cmd,
                cwd=str(workdir),
                stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=merged_env,
            )
        proc = self._proc
        assert proc is not None  # for type-checker

        # Feed stdin if needed, then close.
        if stdin_text is not None:
            assert proc.stdin is not None
            proc.stdin.write(stdin_text)
            proc.stdin.close()

        # Stream combined output line-by-line.
        assert proc.stdout is not None
        for line in proc.stdout:
            if on_output is not None:
                on_output(line)

        proc.wait()
        with self._lock:
            self._proc = None
        return proc.returncode


# ---------------------------------------------------------------------------
# Concrete adapters
# ---------------------------------------------------------------------------


class ClaudeCodeAdapter(AgentAdapter):
    """Adapter for the ``claude`` CLI (Claude Code)."""

    name = "claude-code"
    command = "claude"

    def run(
        self,
        workdir: Path,
        *,
        on_output: Callable[[str], None] | None = None,
        program_file: str = "program.md",
        env: dict[str, str] | None = None,
    ) -> int:
        prompt = (workdir / ".research" / program_file).read_text(encoding="utf-8")
        cmd = [self.command, "-p", prompt, "--verbose"]
        return self._run_process(cmd, workdir, on_output=on_output, env=env)


class CodexAdapter(AgentAdapter):
    """Adapter for the ``codex`` CLI (OpenAI Codex)."""

    name = "codex"
    command = "codex"

    def run(
        self,
        workdir: Path,
        *,
        on_output: Callable[[str], None] | None = None,
        program_file: str = "program.md",
        env: dict[str, str] | None = None,
    ) -> int:
        prompt = (workdir / ".research" / program_file).read_text(encoding="utf-8")
        cmd = [
            self.command, "exec",
            "-s", self._config.get("sandbox", "workspace-write"),
            "--full-auto",
            prompt,
        ]
        return self._run_process(cmd, workdir, on_output=on_output, env=env)


class AiderAdapter(AgentAdapter):
    """Adapter for the ``aider`` CLI."""

    name = "aider"
    command = "aider"

    def run(
        self,
        workdir: Path,
        *,
        on_output: Callable[[str], None] | None = None,
        program_file: str = "program.md",
        env: dict[str, str] | None = None,
    ) -> int:
        msg_file = workdir / ".research" / program_file
        cmd = [self.command, "--yes-always", "--no-git", "--message-file", str(msg_file)]
        return self._run_process(cmd, workdir, on_output=on_output, env=env)


class GeminiAdapter(AgentAdapter):
    """Adapter for the ``gemini`` CLI."""

    name = "gemini"
    command = "gemini"

    def run(
        self,
        workdir: Path,
        *,
        on_output: Callable[[str], None] | None = None,
        program_file: str = "program.md",
        env: dict[str, str] | None = None,
    ) -> int:
        prompt = (workdir / ".research" / program_file).read_text(encoding="utf-8")
        cmd = [self.command, "-p", prompt]
        return self._run_process(cmd, workdir, on_output=on_output, env=env)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_ADAPTERS: dict[str, type[AgentAdapter]] = {
    "claude-code": ClaudeCodeAdapter,
    "codex": CodexAdapter,
    "aider": AiderAdapter,
    "gemini": GeminiAdapter,
}


def create_agent(name: str, config: dict[str, Any] | None = None) -> AgentAdapter:
    """Instantiate an agent adapter by *name*.

    Raises ``ValueError`` if *name* is not in the adapter registry.
    """
    cls = _ADAPTERS.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown agent {name!r}. Available: {sorted(_ADAPTERS)}"
        )
    return cls(config)


# ---------------------------------------------------------------------------
# High-level Agent wrapper
# ---------------------------------------------------------------------------


class Agent:
    """High-level wrapper that pairs an adapter with program-file management.

    Parameters
    ----------
    adapter:
        A concrete ``AgentAdapter`` instance.
    """

    def __init__(self, adapter: AgentAdapter) -> None:
        self.adapter = adapter

    def run(
        self,
        workdir: Path,
        *,
        program_content: str = "",
        program_file: str = "program.md",
        env: dict[str, str] | None = None,
        on_output: Callable[[str], None] | None = None,
    ) -> int:
        """Write *program_content* to ``.research/<program_file>`` then run the agent."""
        dest = workdir / ".research" / program_file
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(program_content, encoding="utf-8")
        return self.adapter.run(
            workdir, on_output=on_output, program_file=program_file, env=env,
        )

    def terminate(self) -> None:
        """Terminate the running agent subprocess."""
        self.adapter.terminate()
