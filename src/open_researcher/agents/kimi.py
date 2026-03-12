"""Kimi CLI agent adapter."""

from pathlib import Path
from typing import Callable

from open_researcher.agents import register
from open_researcher.agents.base import AgentAdapter


@register
class KimiAdapter(AgentAdapter):
    name = "kimi-cli"
    command = "kimi"

    def _build_flags(self) -> list[str]:
        """Build configurable flags from adapter config."""
        model = str(self._config.get("model", "")).strip()
        agent_name = str(self._config.get("agent", "")).strip()
        agent_file = str(self._config.get("agent_file", "")).strip()
        extra = self._config.get("extra_flags", [])
        flags: list[str] = []
        if model:
            flags.extend(["--model", model])
        if agent_file:
            flags.extend(["--agent-file", agent_file])
        elif agent_name:
            flags.extend(["--agent", agent_name])
        flags.extend(extra)
        return flags

    def build_command(self, program_md: Path, workdir: Path) -> list[str]:
        return [self.command, "--print", "--output-format", "text", "-p", str(program_md), *self._build_flags()]

    def run(
        self,
        workdir: Path,
        on_output: Callable[[str], None] | None = None,
        program_file: str = "program.md",
        env: dict[str, str] | None = None,
    ) -> int:
        program_md = workdir / ".research" / program_file
        try:
            prompt = program_md.read_text()
        except FileNotFoundError:
            msg = f"[kimi-cli] program file not found: {program_md}"
            if on_output:
                on_output(msg)
            return 1
        cmd = [self.command, "--print", "--output-format", "text", "-p", prompt, *self._build_flags()]
        return self._run_process(cmd, workdir, on_output, env=env)
