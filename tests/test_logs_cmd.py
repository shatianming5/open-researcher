"""Tests for the logs CLI subcommand."""

import pytest
from typer.testing import CliRunner

from open_researcher.cli import app

runner = CliRunner()


@pytest.fixture
def research_dir(tmp_path, monkeypatch):
    """Set up a minimal .research directory with a log file."""
    research = tmp_path / ".research"
    research.mkdir()
    monkeypatch.chdir(tmp_path)
    return research


def test_logs_show_last(research_dir):
    """Shows last N lines of the log file."""
    lines = [f"Line {i}" for i in range(100)]
    (research_dir / "run.log").write_text("\n".join(lines))

    result = runner.invoke(app, ["logs", "--last", "5"])
    assert result.exit_code == 0
    output_lines = result.stdout.strip().splitlines()
    assert len(output_lines) == 5
    assert "Line 95" in result.stdout
    assert "Line 99" in result.stdout


def test_logs_show_default_last(research_dir):
    """Default --last is 50 lines."""
    lines = [f"Line {i}" for i in range(100)]
    (research_dir / "run.log").write_text("\n".join(lines))

    result = runner.invoke(app, ["logs"])
    assert result.exit_code == 0
    output_lines = result.stdout.strip().splitlines()
    assert len(output_lines) == 50


def test_logs_errors_filter(research_dir):
    """--errors flag filters to only error/traceback lines."""
    log_content = "\n".join(
        [
            "INFO: Starting agent",
            "DEBUG: Loaded config",
            "ERROR: Connection failed",
            "INFO: Retrying...",
            "Traceback (most recent call last):",
            "INFO: Done",
        ]
    )
    (research_dir / "run.log").write_text(log_content)

    result = runner.invoke(app, ["logs", "--errors"])
    assert result.exit_code == 0
    assert "ERROR: Connection failed" in result.stdout
    assert "Traceback" in result.stdout
    assert "Starting agent" not in result.stdout
    assert "Loaded config" not in result.stdout


def test_logs_missing_file(tmp_path, monkeypatch):
    """Logs command fails when run.log does not exist."""
    monkeypatch.chdir(tmp_path)
    # No .research directory at all
    result = runner.invoke(app, ["logs"])
    assert result.exit_code == 1
    assert "No log file" in result.stdout


def test_logs_errors_no_matches(research_dir):
    """--errors with no error lines produces empty output."""
    log_content = "\n".join(["INFO: All good", "DEBUG: No issues", "INFO: Done"])
    (research_dir / "run.log").write_text(log_content)

    result = runner.invoke(app, ["logs", "--errors"])
    assert result.exit_code == 0
    # No error lines, so output should be empty (or only whitespace)
    assert "ERROR" not in result.stdout
    assert "Traceback" not in result.stdout


def test_logs_small_file(research_dir):
    """When log has fewer lines than --last, show all lines."""
    lines = ["Line 0", "Line 1", "Line 2"]
    (research_dir / "run.log").write_text("\n".join(lines))

    result = runner.invoke(app, ["logs", "--last", "10"])
    assert result.exit_code == 0
    assert "Line 0" in result.stdout
    assert "Line 1" in result.stdout
    assert "Line 2" in result.stdout
