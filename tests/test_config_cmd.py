"""Tests for the config CLI subcommand."""

import pytest
import yaml
from typer.testing import CliRunner

from open_researcher.cli import app

runner = CliRunner()


@pytest.fixture
def research_dir(tmp_path, monkeypatch):
    """Set up a minimal .research directory."""
    research = tmp_path / ".research"
    research.mkdir()
    monkeypatch.chdir(tmp_path)
    return research


def test_config_show(research_dir):
    """Show command prints config content."""
    config_data = {
        "mode": "autonomous",
        "metrics": {"primary": {"name": "accuracy", "direction": "maximize"}},
    }
    (research_dir / "config.yaml").write_text(yaml.dump(config_data))
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    assert "autonomous" in result.stdout
    assert "accuracy" in result.stdout


def test_config_show_missing(tmp_path, monkeypatch):
    """Show command fails when config.yaml does not exist."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 1


def test_config_validate_valid(research_dir):
    """Validate reports no warnings for complete configuration."""
    config_data = {
        "mode": "autonomous",
        "metrics": {"primary": {"name": "accuracy", "direction": "maximize"}},
    }
    (research_dir / "config.yaml").write_text(yaml.dump(config_data))
    result = runner.invoke(app, ["config", "validate"])
    assert result.exit_code == 0
    assert "valid" in result.stdout.lower()


def test_config_validate_incomplete(research_dir):
    """Validate shows warnings for missing metric fields."""
    config_data = {"mode": "autonomous"}
    (research_dir / "config.yaml").write_text(yaml.dump(config_data))
    result = runner.invoke(app, ["config", "validate"])
    assert result.exit_code == 0
    assert "WARN" in result.stdout
    assert "metrics.primary.name" in result.stdout
    assert "metrics.primary.direction" in result.stdout


def test_config_validate_partial(research_dir):
    """Validate shows warning when only metric name is set but direction is missing."""
    config_data = {
        "mode": "autonomous",
        "metrics": {"primary": {"name": "loss"}},
    }
    (research_dir / "config.yaml").write_text(yaml.dump(config_data))
    result = runner.invoke(app, ["config", "validate"])
    assert result.exit_code == 0
    assert "metrics.primary.direction" in result.stdout
    assert "metrics.primary.name" not in result.stdout


def test_config_validate_no_research(tmp_path, monkeypatch):
    """Validate fails when .research directory does not exist."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["config", "validate"])
    assert result.exit_code == 1
