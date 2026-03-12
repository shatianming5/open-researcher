"""Codex CLI agent adapter."""

from pathlib import Path
from typing import Callable

from paperfarm.agents import register
from paperfarm.agents.base import AgentAdapter

_DEFAULT_MODEL = "gpt-5.3-codex"
_DEFAULT_SANDBOX = "workspace-write"
_SANDBOX_ALIAS_FLAGS = {
    "full-auto": ["--full-auto"],
}


@register
class CodexAdapter(AgentAdapter):
    name = "codex"
    command = "codex"

    @staticmethod
    def _shared_writable_dirs(workdir: Path) -> list[str]:
        research_dir = workdir / ".research"
        if not research_dir.is_symlink():
            return []
        try:
            resolved_workdir = workdir.resolve()
            resolved_research = research_dir.resolve()
        except OSError:
            return []
        try:
            resolved_research.relative_to(resolved_workdir)
            return []
        except ValueError:
            return [str(resolved_research)]

    def build_command(self, program_md: Path, workdir: Path) -> list[str]:
        model = self._config.get("model", _DEFAULT_MODEL)
        sandbox = self._config.get("sandbox", _DEFAULT_SANDBOX)
        extra = self._config.get("extra_flags", [])
        sandbox_flags = _SANDBOX_ALIAS_FLAGS.get(sandbox, ["--sandbox", sandbox])
        add_dirs: list[str] = []
        if sandbox in {"workspace-write", "full-auto"}:
            for path in self._shared_writable_dirs(workdir):
                add_dirs.extend(["--add-dir", path])
        return [self.command, "exec", "-m", model, *sandbox_flags, *add_dirs, *extra, "-"]

    def run(
        self,
        workdir: Path,
        on_output: Callable[[str], None] | None = None,
        program_file: str = "program.md",
        env: dict[str, str] | None = None,
    ) -> int:
        program_md = workdir / ".research" / program_file
        cmd = self.build_command(program_md, workdir)
        try:
            prompt = program_md.read_text()
        except FileNotFoundError:
            msg = f"[codex] program file not found: {program_md}"
            if on_output:
                on_output(msg)
            return 1
        return self._run_process(cmd, workdir, on_output, stdin_text=prompt, env=env)
