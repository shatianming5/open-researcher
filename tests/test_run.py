"""Tests for the run command."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _setup_research_dir(repo: Path):
    """Create a minimal .research/ directory for testing."""
    research = repo / ".research"
    research.mkdir()
    (research / "program.md").write_text("Test program instructions")
    (research / "config.yaml").write_text(
        "mode: autonomous\nmetrics:\n  primary:\n    name: accuracy\n    direction: higher_is_better\n"
    )
    (research / "results.tsv").write_text(
        "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
    )
    (research / "project-understanding.md").write_text("# Project\n")
    (research / "evaluation.md").write_text("# Evaluation\n")
    scripts = research / "scripts"
    scripts.mkdir()
    (scripts / "record.py").write_text("")
    (scripts / "rollback.sh").write_text("")
    return repo


def test_run_fails_without_research_dir():
    from open_researcher.run_cmd import do_run

    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(SystemExit):
            do_run(Path(tmp), agent_name=None, dry_run=False)


def test_run_fails_when_no_agent_found():
    from open_researcher.run_cmd import do_run

    with tempfile.TemporaryDirectory() as tmp:
        _setup_research_dir(Path(tmp))
        with patch("open_researcher.run_cmd.detect_agent", return_value=None), pytest.raises(SystemExit):
            do_run(Path(tmp), agent_name=None, dry_run=False)


def test_run_dry_run_prints_command(capsys):
    from open_researcher.run_cmd import do_run

    with tempfile.TemporaryDirectory() as tmp:
        repo = _setup_research_dir(Path(tmp))
        mock_agent = MagicMock()
        mock_agent.name = "test-agent"
        mock_agent.build_command.return_value = ["test-cmd", "--flag"]

        with patch("open_researcher.run_cmd.get_agent", return_value=mock_agent):
            do_run(repo, agent_name="test-agent", dry_run=True)

        captured = capsys.readouterr()
        assert "test-agent" in captured.out


def test_run_launches_agent():
    from open_researcher.run_cmd import do_run

    with tempfile.TemporaryDirectory() as tmp:
        repo = _setup_research_dir(Path(tmp))
        mock_agent = MagicMock()
        mock_agent.name = "test-agent"
        mock_agent.run.return_value = 0

        mock_app = MagicMock()
        mock_app_cls = MagicMock(return_value=mock_app)

        with (
            patch("open_researcher.run_cmd.get_agent", return_value=mock_agent),
            patch("open_researcher.tui.app.ResearchApp", mock_app_cls),
            patch("open_researcher.status_cmd.print_status", return_value=None),
        ):
            do_run(repo, agent_name="test-agent", dry_run=False)

        mock_agent.run.assert_called_once()


def test_run_multi_fails_without_research_dir(tmp_path, monkeypatch):
    """Multi-agent mode requires .research/ directory."""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        from open_researcher.run_cmd import do_run_multi

        do_run_multi(repo_path=tmp_path, idea_agent_name=None, exp_agent_name=None, dry_run=False)


def test_run_multi_dry_run_shows_master(capsys):
    from open_researcher.run_cmd import do_run_multi

    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        research = repo / ".research"
        research.mkdir()
        (research / "idea_program.md").write_text("Idea instructions")
        (research / "experiment_program.md").write_text("Master instructions")

        mock_idea = MagicMock()
        mock_idea.name = "claude-code"
        mock_exp = MagicMock()
        mock_exp.name = "claude-code"

        with patch("open_researcher.run_cmd.get_agent", side_effect=[mock_idea, mock_exp]):
            do_run_multi(repo, idea_agent_name="claude-code", exp_agent_name="claude-code", dry_run=True)

        captured = capsys.readouterr()
        assert "Idea Agent" in captured.out
        assert "Experiment Master" in captured.out
