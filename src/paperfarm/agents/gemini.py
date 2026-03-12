"""Gemini CLI agent adapter."""

from pathlib import Path
from typing import Callable

from paperfarm.agents import register
from paperfarm.agents.base import AgentAdapter

_DEFAULT_MODEL = "gemini-3.1-pro"


@register
class GeminiAdapter(AgentAdapter):
    name = "gemini-cli"
    command = "gemini"

    def _build_flags(self) -> list[str]:
        """Build configurable flags from adapter config."""
        model = self._config.get("model", _DEFAULT_MODEL)
        sandbox = self._config.get("sandbox", "")
        extra = self._config.get("extra_flags", [])
        flags = ["--model", model]
        if sandbox:
            flags.extend(["--sandbox", sandbox])
        flags.extend(extra)
        return flags

    def build_command(self, program_md: Path, workdir: Path) -> list[str]:
        return [self.command, "-p", str(program_md), *self._build_flags()]

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
            msg = f"[gemini] program file not found: {program_md}"
            if on_output:
                on_output(msg)
            return 1
        cmd = [self.command, "-p", prompt, *self._build_flags()]
        return self._run_process(cmd, workdir, on_output, env=env)
