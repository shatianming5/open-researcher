"""Tests for the CLI entry point."""

from pathlib import Path

from typer.testing import CliRunner

from open_researcher.cli import app

runner = CliRunner()


def test_init_via_cli():
    with runner.isolated_filesystem():
        Path(".git").mkdir()
        result = runner.invoke(app, ["init", "--tag", "test1"])
        assert result.exit_code == 0
        assert Path(".research").is_dir()
        assert Path(".research/program.md").exists()


def test_init_refuses_duplicate():
    with runner.isolated_filesystem():
        Path(".git").mkdir()
        Path(".research").mkdir()
        result = runner.invoke(app, ["init"])
        assert result.exit_code == 1


def test_status_without_research():
    with runner.isolated_filesystem():
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 1


def test_results_without_research():
    with runner.isolated_filesystem():
        result = runner.invoke(app, ["results"])
        assert result.exit_code == 1


def test_export_without_research():
    with runner.isolated_filesystem():
        result = runner.invoke(app, ["export"])
        assert result.exit_code == 1


def test_run_without_research():
    with runner.isolated_filesystem():
        result = runner.invoke(app, ["run"])
        assert result.exit_code == 1


def test_run_dry_run():
    with runner.isolated_filesystem():
        Path(".git").mkdir()
        result = runner.invoke(app, ["init", "--tag", "clitest"])
        assert result.exit_code == 0

        from unittest.mock import MagicMock, patch

        mock_agent = MagicMock()
        mock_agent.name = "mock-agent"
        mock_agent.build_command.return_value = ["mock-cmd", "--test"]

        with patch("open_researcher.run_cmd.detect_agent", return_value=mock_agent):
            result = runner.invoke(app, ["run", "--dry-run"])
            assert result.exit_code == 0
            assert "mock-agent" in result.stdout


def test_start_without_git():
    """start should fail without git repo."""
    with runner.isolated_filesystem():
        result = runner.invoke(app, ["start"])
        assert result.exit_code == 1


def test_start_help():
    """start --help should show the command."""
    result = runner.invoke(app, ["start", "--help"])
    assert result.exit_code == 0
    assert "start" in result.stdout.lower() or "Start" in result.stdout


def test_start_headless_requires_goal():
    """start --headless without --goal should fail."""
    with runner.isolated_filesystem():
        Path(".git").mkdir()
        result = runner.invoke(app, ["start", "--headless"])
        assert result.exit_code != 0
        assert "goal" in result.stdout.lower() or "goal" in str(result.exception).lower()


def test_start_headless_help():
    """start --help should show --headless and --max-experiments flags."""
    result = runner.invoke(app, ["start", "--help"])
    assert result.exit_code == 0
    assert "--headless" in result.stdout
    assert "--max-experiments" in result.stdout
    assert "--goal" in result.stdout
