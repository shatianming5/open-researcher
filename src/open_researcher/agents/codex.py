"""Codex CLI agent adapter."""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from open_researcher.agents import register
from open_researcher.agents.base import AgentAdapter


@register
class CodexAdapter(AgentAdapter):
    name = "codex"
    command = "codex"

    def __init__(self):
        self._proc: subprocess.Popen | None = None

    def check_installed(self) -> bool:
        return shutil.which(self.command) is not None

    def build_command(self, program_md: Path, workdir: Path) -> list[str]:
        # Use "-" to read prompt from stdin (program.md can be very long)
        return [self.command, "exec", "--full-auto", "-"]

    def run(
        self,
        workdir: Path,
        on_output: Callable[[str], None] | None = None,
        program_file: str = "program.md",
    ) -> int:
        program_md = workdir / ".research" / program_file
        cmd = self.build_command(program_md, workdir)
        prompt = program_md.read_text()
        proc = subprocess.Popen(
            cmd,
            cwd=str(workdir),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        proc.stdin.write(prompt)
        proc.stdin.close()
        self._proc = proc
        for line in proc.stdout:
            if on_output:
                on_output(line.rstrip("\n"))
        return proc.wait()

    def terminate(self) -> None:
        """Terminate the running agent subprocess."""
        if self._proc and self._proc.poll() is None:
            try:
                os.killpg(os.getpgid(self._proc.pid), 15)
            except (OSError, ProcessLookupError):
                pass
