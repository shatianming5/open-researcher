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
