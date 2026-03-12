"""Claude Code agent adapter."""

import json
from pathlib import Path
from typing import Callable

from paperfarm.agents import register
from paperfarm.agents.base import AgentAdapter
from paperfarm.token_tracking import TokenMetrics

_DEFAULT_TOOLS = "Edit,Write,Bash,Read,Glob,Grep"


@register
class ClaudeCodeAdapter(AgentAdapter):
    name = "claude-code"
    command = "claude"

    def _build_flags(self) -> list[str]:
        """Build configurable flags from adapter config."""
        tools = self._config.get("allowed_tools", _DEFAULT_TOOLS)
        model = self._config.get("model", "")
        extra = self._config.get("extra_flags", [])
        flags = ["--allowedTools", tools]
        if model:
            flags.extend(["--model", model])
        flags.extend(extra)
        flags.extend(["--output-format", "stream-json"])
        return flags

    def build_command(self, program_md: Path, workdir: Path) -> list[str]:
        return [self.command, "-p", str(program_md), *self._build_flags()]

    def _try_parse_token_line(self, line: str) -> TokenMetrics | None:
        """Parse token usage from Claude Code stream-json output."""
        try:
            data = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            return None
        if data.get("type") != "result":
            return None
        usage = data.get("usage", {})
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        if input_tokens or output_tokens:
            return TokenMetrics(tokens_input=input_tokens, tokens_output=output_tokens)
        return None

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
            msg = f"[claude-code] program file not found: {program_md}"
            if on_output:
                on_output(msg)
            return 1
        cmd = [self.command, "-p", prompt, *self._build_flags()]

        def _stream_json_output(line: str) -> None:
            """Extract human-readable text from stream-json and forward to on_output."""
            if not on_output:
                return
            try:
                data = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                on_output(line)
                return
            msg_type = data.get("type", "")
            if msg_type == "assistant":
                for block in data.get("content", []):
                    if block.get("type") == "text" and block.get("text"):
                        on_output(block["text"])
            elif msg_type == "result":
                result_text = data.get("result", "")
                if result_text:
                    on_output(str(result_text))

        return self._run_process(cmd, workdir, _stream_json_output, env=env)
