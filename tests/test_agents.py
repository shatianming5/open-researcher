"""Tests for agent adapter base class and registry."""

import shutil
import tempfile
from pathlib import Path

import pytest

from paperfarm.agents import detect_agent, get_agent, list_agents
from paperfarm.agents.base import AgentAdapter


class DummyAgent(AgentAdapter):
    name = "dummy"
    command = "dummy-bin"

    def check_installed(self) -> bool:
        return True

    def build_command(self, program_md, workdir):
        return ["dummy-bin", "--prompt", str(program_md)]

    def run(self, workdir, on_output=None):
        return 0


def test_adapter_interface():
    agent = DummyAgent()
    assert agent.name == "dummy"
    assert agent.check_installed() is True
    cmd = agent.build_command(Path("/tmp/program.md"), Path("/tmp/work"))
    assert cmd[0] == "dummy-bin"


def test_list_agents():
    agents = list_agents()
    assert isinstance(agents, dict)
    assert "claude-code" in agents
    assert "codex" in agents
    assert "aider" in agents
    assert "opencode" in agents
    assert "gemini-cli" in agents


def test_get_agent_known():
    agent = get_agent("claude-code")
    assert agent.name == "claude-code"


def test_get_agent_unknown():
    with pytest.raises(KeyError):
        get_agent("nonexistent-agent")


def test_detect_agent_returns_none_when_none_installed(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda x: None)
    result = detect_agent()
    assert result is None


def test_claude_code_build_command():
    from paperfarm.agents.claude_code import ClaudeCodeAdapter

    agent = ClaudeCodeAdapter()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write("test prompt")
        f.flush()
        cmd = agent.build_command(Path(f.name), Path("/tmp/work"))
    assert cmd[0] == "claude"
    assert "-p" in cmd


def test_codex_build_command():
    from paperfarm.agents.codex import CodexAdapter

    agent = CodexAdapter()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write("test prompt")
        f.flush()
        cmd = agent.build_command(Path(f.name), Path("/tmp/work"))
    assert cmd == ["codex", "exec", "-m", "gpt-5.3-codex", "--sandbox", "workspace-write", "-"]


def test_codex_build_command_supports_full_auto_alias():
    from paperfarm.agents.codex import CodexAdapter

    agent = CodexAdapter(config={"sandbox": "full-auto", "extra_flags": ["--skip-git-repo-check"]})
    cmd = agent.build_command(Path("/tmp/program.md"), Path("/tmp/work"))
    assert cmd == [
        "codex",
        "exec",
        "-m",
        "gpt-5.3-codex",
        "--full-auto",
        "--skip-git-repo-check",
        "-",
    ]


def test_codex_build_command_adds_external_shared_research_dir(tmp_path):
    from paperfarm.agents.codex import CodexAdapter

    shared_research = tmp_path / "shared-research"
    shared_research.mkdir()
    workdir = tmp_path / "worker"
    workdir.mkdir()
    (workdir / ".research").symlink_to(shared_research, target_is_directory=True)

    agent = CodexAdapter()
    cmd = agent.build_command(shared_research / "program.md", workdir)

    assert "--add-dir" in cmd
    add_dir_idx = cmd.index("--add-dir")
    assert cmd[add_dir_idx + 1] == str(shared_research.resolve())


def test_aider_build_command():
    from paperfarm.agents.aider import AiderAdapter

    agent = AiderAdapter()
    cmd = agent.build_command(Path("/tmp/program.md"), Path("/tmp/work"))
    assert cmd[0] == "aider"


def test_opencode_build_command():
    from paperfarm.agents.opencode import OpencodeAdapter

    agent = OpencodeAdapter()
    agent._supports_run_subcommand = True
    cmd = agent.build_command(Path("/tmp/program.md"), Path("/tmp/work"))
    assert cmd == ["opencode", "run", "<prompt>"]


def test_opencode_build_command_falls_back_to_top_level_prompt():
    from paperfarm.agents.opencode import OpencodeAdapter

    agent = OpencodeAdapter()
    agent._supports_run_subcommand = False
    cmd = agent.build_command(Path("/tmp/program.md"), Path("/tmp/work"))
    assert cmd == ["opencode", "--prompt", "<prompt>"]


def test_opencode_probe_detects_run_subcommand(monkeypatch):
    from paperfarm.agents.opencode import OpencodeAdapter

    class Result:
        returncode = 0

    calls = []

    def fake_run(cmd, cwd=None, capture_output=True, text=True):
        calls.append((cmd, cwd))
        return Result()

    monkeypatch.setattr("paperfarm.agents.opencode.subprocess.run", fake_run)

    agent = OpencodeAdapter()
    cmd = agent.build_command(Path("/tmp/program.md"), Path("/tmp/work"))

    assert calls == [(["opencode", "run", "--help"], "/tmp/work")]
    assert cmd == ["opencode", "run", "<prompt>"]


def test_opencode_config_includes_model_agent_and_extra_flags():
    from paperfarm.agents.opencode import OpencodeAdapter

    agent = OpencodeAdapter(config={"model": "openai/gpt-5", "agent": "builder", "extra_flags": ["--share"]})
    agent._supports_run_subcommand = True
    cmd = agent.build_command(Path("/tmp/program.md"), Path("/tmp/work"))
    assert cmd == ["opencode", "run", "--model", "openai/gpt-5", "--agent", "builder", "--share", "<prompt>"]


def test_opencode_run_prefers_run_subcommand(tmp_path, monkeypatch):
    from paperfarm.agents.opencode import OpencodeAdapter

    research = tmp_path / ".research"
    research.mkdir()
    (research / "program.md").write_text("test prompt", encoding="utf-8")

    agent = OpencodeAdapter(config={"model": "openai/gpt-5", "agent": "builder", "extra_flags": ["--share"]})
    agent._supports_run_subcommand = True
    calls = {}

    def fake_run_process(cmd, workdir, on_output=None, stdin_text=None, env=None):
        calls["cmd"] = cmd
        calls["workdir"] = workdir
        calls["env"] = env
        calls["stdin_text"] = stdin_text
        return 0

    monkeypatch.setattr(agent, "_run_process", fake_run_process)

    result = agent.run(tmp_path, env={"OPEN_RESEARCHER_PROTOCOL": "research-v1"})

    assert result == 0
    assert calls["workdir"] == tmp_path
    assert calls["stdin_text"] is None
    assert calls["env"] == {"OPEN_RESEARCHER_PROTOCOL": "research-v1"}
    assert calls["cmd"] == [
        "opencode",
        "run",
        "--model",
        "openai/gpt-5",
        "--agent",
        "builder",
        "--share",
        "test prompt",
    ]


def test_opencode_run_falls_back_to_top_level_prompt(tmp_path, monkeypatch):
    from paperfarm.agents.opencode import OpencodeAdapter

    research = tmp_path / ".research"
    research.mkdir()
    (research / "program.md").write_text("test prompt", encoding="utf-8")

    agent = OpencodeAdapter()
    agent._supports_run_subcommand = False
    calls = {}

    def fake_run_process(cmd, workdir, on_output=None, stdin_text=None, env=None):
        calls["cmd"] = cmd
        return 0

    monkeypatch.setattr(agent, "_run_process", fake_run_process)

    result = agent.run(tmp_path)

    assert result == 0
    assert calls["cmd"] == ["opencode", "--prompt", "test prompt"]


def test_opencode_run_reports_missing_program_file(tmp_path):
    from paperfarm.agents.opencode import OpencodeAdapter

    agent = OpencodeAdapter()
    output = []

    result = agent.run(tmp_path, on_output=output.append)

    assert result == 1
    assert output == [f"[opencode] program file not found: {tmp_path / '.research' / 'program.md'}"]


def test_check_installed_uses_shutil_which(monkeypatch):
    from paperfarm.agents.claude_code import ClaudeCodeAdapter

    agent = ClaudeCodeAdapter()
    monkeypatch.setattr(shutil, "which", lambda x: "/usr/bin/claude" if x == "claude" else None)
    assert agent.check_installed() is True
    monkeypatch.setattr(shutil, "which", lambda x: None)
    assert agent.check_installed() is False


# ---- Agent config tests ----


def test_claude_code_config_custom_model():
    from paperfarm.agents.claude_code import ClaudeCodeAdapter

    agent = ClaudeCodeAdapter(config={"model": "claude-sonnet-4-5-20250514", "allowed_tools": "Bash,Read"})
    cmd = agent.build_command(Path("/tmp/program.md"), Path("/tmp/work"))
    assert "--model" in cmd
    assert "claude-sonnet-4-5-20250514" in cmd
    assert "Bash,Read" in cmd


def test_claude_code_config_extra_flags():
    from paperfarm.agents.claude_code import ClaudeCodeAdapter

    agent = ClaudeCodeAdapter(config={"extra_flags": ["--max-turns", "50"]})
    cmd = agent.build_command(Path("/tmp/program.md"), Path("/tmp/work"))
    assert "--max-turns" in cmd
    assert "50" in cmd


def test_codex_config_custom_model():
    from paperfarm.agents.codex import CodexAdapter

    agent = CodexAdapter(config={"model": "gpt-5.2", "sandbox": "danger-full-access"})
    cmd = agent.build_command(Path("/tmp/program.md"), Path("/tmp/work"))
    assert "-m" in cmd
    idx = cmd.index("-m")
    assert cmd[idx + 1] == "gpt-5.2"
    assert "--sandbox" in cmd
    assert "danger-full-access" in cmd


def test_codex_default_model():
    from paperfarm.agents.codex import CodexAdapter

    agent = CodexAdapter()
    cmd = agent.build_command(Path("/tmp/program.md"), Path("/tmp/work"))
    assert "gpt-5.3-codex" in cmd
    assert "--sandbox" in cmd
    assert "workspace-write" in cmd


def test_aider_config_model():
    from paperfarm.agents.aider import AiderAdapter

    agent = AiderAdapter(config={"model": "gpt-4o"})
    cmd = agent.build_command(Path("/tmp/program.md"), Path("/tmp/work"))
    assert "--model" in cmd
    assert "gpt-4o" in cmd


def test_get_agent_with_config():
    agent = get_agent("claude-code", config={"model": "test-model"})
    assert agent._config.get("model") == "test-model"


def test_detect_agent_with_configs(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda x: "/usr/bin/claude" if x == "claude" else None)
    agent = detect_agent(configs={"claude-code": {"model": "custom-model"}})
    assert agent is not None
    assert agent._config.get("model") == "custom-model"


# ---- Gemini adapter tests ----


def test_gemini_build_command():
    from paperfarm.agents.gemini import GeminiAdapter

    agent = GeminiAdapter()
    cmd = agent.build_command(Path("/tmp/program.md"), Path("/tmp/work"))
    assert cmd == ["gemini", "-p", "/tmp/program.md", "--model", "gemini-3.1-pro"]


def test_gemini_build_command_with_config():
    from paperfarm.agents.gemini import GeminiAdapter

    agent = GeminiAdapter(config={"model": "gemini-2.5-flash", "sandbox": "auto", "extra_flags": ["--debug"]})
    cmd = agent.build_command(Path("/tmp/program.md"), Path("/tmp/work"))
    assert cmd == [
        "gemini",
        "-p",
        "/tmp/program.md",
        "--model",
        "gemini-2.5-flash",
        "--sandbox",
        "auto",
        "--debug",
    ]


def test_gemini_run_success(tmp_path, monkeypatch):
    from paperfarm.agents.gemini import GeminiAdapter

    research = tmp_path / ".research"
    research.mkdir()
    (research / "program.md").write_text("test prompt", encoding="utf-8")

    agent = GeminiAdapter(config={"model": "gemini-3.1-pro"})
    calls = {}

    def fake_run_process(cmd, workdir, on_output=None, stdin_text=None, env=None):
        calls["cmd"] = cmd
        calls["workdir"] = workdir
        calls["env"] = env
        return 0

    monkeypatch.setattr(agent, "_run_process", fake_run_process)

    result = agent.run(tmp_path, env={"GEMINI_API_KEY": "test-key"})

    assert result == 0
    assert calls["workdir"] == tmp_path
    assert calls["env"] == {"GEMINI_API_KEY": "test-key"}
    assert calls["cmd"] == ["gemini", "-p", "test prompt", "--model", "gemini-3.1-pro"]


def test_gemini_run_missing_program_file(tmp_path):
    from paperfarm.agents.gemini import GeminiAdapter

    agent = GeminiAdapter()
    output = []

    result = agent.run(tmp_path, on_output=output.append)

    assert result == 1
    assert output == [f"[gemini] program file not found: {tmp_path / '.research' / 'program.md'}"]


def test_gemini_default_model():
    from paperfarm.agents.gemini import GeminiAdapter

    agent = GeminiAdapter()
    cmd = agent.build_command(Path("/tmp/program.md"), Path("/tmp/work"))
    assert "--model" in cmd
    assert "gemini-3.1-pro" in cmd
    # no --sandbox when not configured
    assert "--sandbox" not in cmd
