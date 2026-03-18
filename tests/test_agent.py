"""Tests for paperfarm.agent — adapter pattern and Agent wrapper."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from paperfarm.agent import (
    Agent,
    AgentAdapter,
    AiderAdapter,
    ClaudeCodeAdapter,
    CodexAdapter,
    GeminiAdapter,
    _ADAPTERS,
    create_agent,
)


# ---------------------------------------------------------------------------
# TestAgentAdapter — factory & base behaviour
# ---------------------------------------------------------------------------


class TestAgentAdapter:
    """Tests for the adapter factory and base class."""

    def test_create_known_agents(self):
        for name in ("claude-code", "codex", "aider", "gemini"):
            adapter = create_agent(name)
            assert adapter.name == name
            assert isinstance(adapter, AgentAdapter)

    def test_create_unknown_agent_raises(self):
        with pytest.raises(ValueError, match="Unknown agent"):
            create_agent("nonexistent-agent")

    def test_create_with_config(self):
        adapter = create_agent("codex", config={"sandbox": "read-only"})
        assert adapter._config == {"sandbox": "read-only"}

    def test_create_with_none_config(self):
        adapter = create_agent("claude-code")
        assert adapter._config == {}

    def test_adapter_registry_contains_all(self):
        assert set(_ADAPTERS.keys()) == {"claude-code", "codex", "aider", "gemini"}

    def test_adapter_types(self):
        assert _ADAPTERS["claude-code"] is ClaudeCodeAdapter
        assert _ADAPTERS["codex"] is CodexAdapter
        assert _ADAPTERS["aider"] is AiderAdapter
        assert _ADAPTERS["gemini"] is GeminiAdapter

    @patch("shutil.which", return_value="/usr/local/bin/claude")
    def test_check_installed_true(self, mock_which):
        adapter = create_agent("claude-code")
        assert adapter.check_installed() is True
        mock_which.assert_called_once_with("claude")

    @patch("shutil.which", return_value=None)
    def test_check_installed_false(self, mock_which):
        adapter = create_agent("claude-code")
        assert adapter.check_installed() is False

    def test_terminate_without_running_process(self):
        """Calling terminate when no process is running should be a no-op."""
        adapter = create_agent("claude-code")
        adapter.terminate()  # should not raise


# ---------------------------------------------------------------------------
# TestAgent — high-level wrapper
# ---------------------------------------------------------------------------


class TestAgent:
    """Tests for the Agent high-level wrapper."""

    def test_run_writes_program_file(self, tmp_path: Path):
        """Agent.run() must write program_content to .research/<program_file>."""
        mock_adapter = MagicMock(spec=AgentAdapter)
        mock_adapter.run.return_value = 0

        agent = Agent(mock_adapter)
        rc = agent.run(
            tmp_path,
            program_content="Do the experiment",
            program_file="experiment.md",
        )

        assert rc == 0
        dest = tmp_path / ".research" / "experiment.md"
        assert dest.exists()
        assert dest.read_text(encoding="utf-8") == "Do the experiment"

    def test_run_uses_default_program_file(self, tmp_path: Path):
        mock_adapter = MagicMock(spec=AgentAdapter)
        mock_adapter.run.return_value = 0

        agent = Agent(mock_adapter)
        agent.run(tmp_path, program_content="hello")

        dest = tmp_path / ".research" / "program.md"
        assert dest.exists()
        assert dest.read_text(encoding="utf-8") == "hello"

    def test_run_passes_env_to_adapter(self, tmp_path: Path):
        mock_adapter = MagicMock(spec=AgentAdapter)
        mock_adapter.run.return_value = 0

        agent = Agent(mock_adapter)
        env = {"MY_VAR": "hello"}
        agent.run(tmp_path, program_content="x", env=env)

        _, kwargs = mock_adapter.run.call_args
        assert kwargs["env"] == {"MY_VAR": "hello"}

    def test_run_passes_on_output_to_adapter(self, tmp_path: Path):
        mock_adapter = MagicMock(spec=AgentAdapter)
        mock_adapter.run.return_value = 0
        callback = MagicMock()

        agent = Agent(mock_adapter)
        agent.run(tmp_path, program_content="x", on_output=callback)

        _, kwargs = mock_adapter.run.call_args
        assert kwargs["on_output"] is callback

    def test_run_returns_adapter_exit_code(self, tmp_path: Path):
        mock_adapter = MagicMock(spec=AgentAdapter)
        mock_adapter.run.return_value = 42

        agent = Agent(mock_adapter)
        assert agent.run(tmp_path, program_content="x") == 42

    def test_terminate_delegates_to_adapter(self):
        mock_adapter = MagicMock(spec=AgentAdapter)
        agent = Agent(mock_adapter)
        agent.terminate()
        mock_adapter.terminate.assert_called_once()

    def test_run_creates_research_dir(self, tmp_path: Path):
        """The .research/ directory should be created automatically."""
        mock_adapter = MagicMock(spec=AgentAdapter)
        mock_adapter.run.return_value = 0

        agent = Agent(mock_adapter)
        agent.run(tmp_path, program_content="content")

        assert (tmp_path / ".research").is_dir()

    def test_run_passes_program_file_to_adapter(self, tmp_path: Path):
        mock_adapter = MagicMock(spec=AgentAdapter)
        mock_adapter.run.return_value = 0

        agent = Agent(mock_adapter)
        agent.run(tmp_path, program_content="x", program_file="custom.md")

        _, kwargs = mock_adapter.run.call_args
        assert kwargs["program_file"] == "custom.md"


# ---------------------------------------------------------------------------
# TestConcreteAdapters — verify command construction
# ---------------------------------------------------------------------------


class TestConcreteAdapters:
    """Verify each adapter reads program and builds correct command."""

    def _setup_program(self, workdir: Path, content: str = "test prompt", filename: str = "program.md") -> None:
        research_dir = workdir / ".research"
        research_dir.mkdir(parents=True, exist_ok=True)
        (research_dir / filename).write_text(content, encoding="utf-8")

    @patch.object(ClaudeCodeAdapter, "_run_process", return_value=0)
    def test_claude_code_cmd(self, mock_run, tmp_path: Path):
        self._setup_program(tmp_path, "my prompt")
        adapter = ClaudeCodeAdapter()
        rc = adapter.run(tmp_path, program_file="program.md")
        assert rc == 0
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "claude"
        assert "-p" in cmd
        prompt_idx = cmd.index("-p")
        assert cmd[prompt_idx + 1] == "my prompt"
        assert "--verbose" in cmd

    @patch.object(CodexAdapter, "_run_process", return_value=0)
    def test_codex_cmd(self, mock_run, tmp_path: Path):
        self._setup_program(tmp_path, "my prompt")
        adapter = CodexAdapter(config={"sandbox": "read-only", "approval_policy": "never"})
        rc = adapter.run(tmp_path, program_file="program.md")
        assert rc == 0
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "codex"
        assert cmd[1] == "exec"
        assert "-s" in cmd
        assert cmd[cmd.index("-s") + 1] == "read-only"
        assert "--full-auto" in cmd
        # prompt is the last positional arg
        assert cmd[-1] == "my prompt"

    @patch.object(CodexAdapter, "_run_process", return_value=0)
    def test_codex_default_config(self, mock_run, tmp_path: Path):
        self._setup_program(tmp_path, "prompt")
        adapter = CodexAdapter()
        adapter.run(tmp_path, program_file="program.md")
        cmd = mock_run.call_args[0][0]
        assert cmd[cmd.index("-s") + 1] == "workspace-write"
        assert "--full-auto" in cmd

    @patch.object(AiderAdapter, "_run_process", return_value=0)
    def test_aider_cmd(self, mock_run, tmp_path: Path):
        self._setup_program(tmp_path, "my prompt")
        adapter = AiderAdapter()
        rc = adapter.run(tmp_path, program_file="program.md")
        assert rc == 0
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "aider"
        assert "--yes-always" in cmd
        assert "--no-git" in cmd
        assert "--message-file" in cmd
        msg_idx = cmd.index("--message-file")
        assert cmd[msg_idx + 1] == str(tmp_path / ".research" / "program.md")

    @patch.object(GeminiAdapter, "_run_process", return_value=0)
    def test_gemini_cmd(self, mock_run, tmp_path: Path):
        self._setup_program(tmp_path, "my prompt")
        adapter = GeminiAdapter()
        rc = adapter.run(tmp_path, program_file="program.md")
        assert rc == 0
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "gemini"
        assert "-p" in cmd
        prompt_idx = cmd.index("-p")
        assert cmd[prompt_idx + 1] == "my prompt"
