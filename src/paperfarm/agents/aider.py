"""Aider agent adapter."""

from pathlib import Path
from typing import Callable

from paperfarm.agents import register
from paperfarm.agents.base import AgentAdapter


@register
class AiderAdapter(AgentAdapter):
    name = "aider"
    command = "aider"

    def build_command(self, program_md: Path, workdir: Path) -> list[str]:
        model = self._config.get("model", "")
        extra = self._config.get("extra_flags", [])
        cmd = [self.command, "--yes-always"]
        if model:
            cmd.extend(["--model", model])
        cmd.extend(["--message-file", str(program_md)])
        cmd.extend(extra)
        return cmd

    def run(
        self,
        workdir: Path,
        on_output: Callable[[str], None] | None = None,
        program_file: str = "program.md",
        env: dict[str, str] | None = None,
    ) -> int:
        program_md = workdir / ".research" / program_file
        if not program_md.exists():
            msg = f"[aider] program file not found: {program_md}"
            if on_output:
                on_output(msg)
            return 1
        cmd = self.build_command(program_md, workdir)
        return self._run_process(cmd, workdir, on_output, env=env)
