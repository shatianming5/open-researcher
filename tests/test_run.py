"""Tests for the interactive research-v1 run command."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _setup_research_dir(repo: Path) -> Path:
    """Create a minimal research-v1 workspace for run-command tests."""
    research = repo / ".research"
    research.mkdir()
    (research / "config.yaml").write_text(
        "mode: autonomous\nresearch:\n  protocol: research-v1\nbootstrap:\n  auto_prepare: false\nmetrics:\n"
        "  primary:\n    name: accuracy\n    direction: higher_is_better\n"
    )
    (research / "results.tsv").write_text(
        "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
    )
    (research / "project-understanding.md").write_text("# Project\n")
    (research / "evaluation.md").write_text("# Evaluation\n")
    (research / "literature.md").write_text("# Literature\n")
    (research / "research-strategy.md").write_text("# Strategy\n")
    (research / "idea_pool.json").write_text('{"ideas": []}\n')
    (research / "scout_program.md").write_text("# scout\n")
    (research / "manager_program.md").write_text("# manager\n")
    (research / "critic_program.md").write_text("# critic\n")
    (research / "experiment_program.md").write_text("# experiment\n")
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


def test_run_dry_run_prints_research_roles(capsys):
    from open_researcher.run_cmd import do_run

    with tempfile.TemporaryDirectory() as tmp:
        repo = _setup_research_dir(Path(tmp))
        mock_agent = MagicMock()
        mock_agent.name = "test-agent"
        mock_agent.build_command.return_value = ["test-cmd", "--flag"]

        with patch("open_researcher.run_cmd.get_agent", return_value=mock_agent):
            do_run(repo, agent_name="test-agent", dry_run=True)

        captured = capsys.readouterr()
        assert "Manager Agent" in captured.out
        assert "Critic Agent" in captured.out
        assert "Experiment Agent" in captured.out
        assert "test-agent" in captured.out


def test_run_launches_graph_protocol():
    from open_researcher.run_cmd import do_run

    with tempfile.TemporaryDirectory() as tmp:
        repo = _setup_research_dir(Path(tmp))
        mock_agent = MagicMock()
        mock_agent.name = "test-agent"

        def fake_run_tui_session(repo_path, **kwargs):
            assert repo_path == repo
            renderer = MagicMock()
            renderer.on_event = MagicMock()
            renderer.make_output_callback.return_value = lambda line: None
            app = MagicMock()
            kwargs["setup"](app, renderer)

        with (
            patch("open_researcher.run_cmd.get_agent", return_value=mock_agent),
            patch("open_researcher.run_cmd.start_daemon", side_effect=lambda target: target()),
            patch("open_researcher.run_cmd.run_tui_session", side_effect=fake_run_tui_session),
            patch("open_researcher.run_cmd.print_exit_summary", return_value=None),
            patch("open_researcher.status_cmd.print_status", return_value=None),
            patch(
                "open_researcher.research_loop.ResearchLoop.run_graph_protocol",
                return_value={"manager": 0, "critic": 0, "exp": 0},
            ) as mock_run_graph,
        ):
            do_run(repo, agent_name="test-agent", dry_run=False)

        mock_run_graph.assert_called_once()
        assert mock_run_graph.call_args.kwargs["parallel_batch_runner"] is not None
