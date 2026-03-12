"""OpenCode agent adapter."""

import subprocess
from pathlib import Path
from typing import Callable

from paperfarm.agents import register
from paperfarm.agents.base import AgentAdapter


@register
class OpencodeAdapter(AgentAdapter):
    name = "opencode"
    command = "opencode"
    _supports_run_subcommand: bool | None = None

    def build_command(self, program_md: Path, workdir: Path) -> list[str]:
        return self._build_prompt_command("<prompt>", workdir=workdir)

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
            msg = f"[opencode] program file not found: {program_md}"
            if on_output:
                on_output(msg)
            return 1
        cmd = self._build_prompt_command(prompt, workdir=workdir)
        return self._run_process(cmd, workdir, on_output, env=env)

    def _build_prompt_command(self, prompt: str, *, workdir: Path | None = None) -> list[str]:
        model = str(self._config.get("model", "")).strip()
        agent_name = str(self._config.get("agent", "")).strip()
        extra = self._config.get("extra_flags", [])
        flags: list[str] = []
        if model:
            flags.extend(["--model", model])
        if agent_name:
            flags.extend(["--agent", agent_name])
        flags.extend(extra)
        if self._supports_run_command(workdir):
            return [self.command, "run", *flags, prompt]
        return [self.command, *flags, "--prompt", prompt]

    def _supports_run_command(self, workdir: Path | None) -> bool:
        if self._supports_run_subcommand is not None:
            return self._supports_run_subcommand
        cwd = str(workdir) if workdir is not None else None
        try:
            result = subprocess.run(
                [self.command, "run", "--help"],
                cwd=cwd,
                capture_output=True,
                text=True,
            )
        except OSError:
            self._supports_run_subcommand = False
            return False
        self._supports_run_subcommand = result.returncode == 0
        return self._supports_run_subcommand
