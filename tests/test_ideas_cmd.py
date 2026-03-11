"""Tests for the ideas CLI subcommand."""

import json

import pytest
from typer.testing import CliRunner

from open_researcher.cli import app

runner = CliRunner()


def _combined_output(result) -> str:
    return (result.stdout or "") + getattr(result, "stderr", "")


@pytest.fixture
def research_dir(tmp_path, monkeypatch):
    """Set up a minimal .research directory with an empty idea pool."""
    research = tmp_path / ".research"
    research.mkdir()
    (research / "idea_pool.json").write_text(json.dumps({"ideas": []}))
    (research / "config.yaml").write_text("research:\n  protocol: research-v1\n")
    monkeypatch.chdir(tmp_path)
    return research


def test_ideas_list(research_dir):
    """List command produces a table with ideas."""
    pool_path = research_dir / "idea_pool.json"
    pool_path.write_text(
        json.dumps(
            {
                "ideas": [
                    {
                        "id": "idea-001",
                        "description": "Try cosine LR",
                        "status": "pending",
                        "priority": 1,
                        "category": "lr",
                        "source": "user",
                    },
                    {
                        "id": "idea-002",
                        "description": "Add augmentation",
                        "status": "done",
                        "priority": 3,
                        "category": "data",
                        "source": "user",
                    },
                ]
            }
        )
    )
    result = runner.invoke(app, ["ideas", "list"])
    assert result.exit_code == 0
    assert "idea-001" in result.stdout
    assert "idea-002" in result.stdout
    assert "Try cosine LR" in result.stdout


def test_ideas_list_filter_status(research_dir):
    """List command filters by status."""
    pool_path = research_dir / "idea_pool.json"
    pool_path.write_text(
        json.dumps(
            {
                "ideas": [
                    {
                        "id": "idea-001",
                        "description": "Pending idea",
                        "status": "pending",
                        "priority": 1,
                        "category": "general",
                    },
                    {
                        "id": "idea-002",
                        "description": "Done idea",
                        "status": "done",
                        "priority": 2,
                        "category": "general",
                    },
                ]
            }
        )
    )
    result = runner.invoke(app, ["ideas", "list", "--status", "pending"])
    assert result.exit_code == 0
    assert "idea-001" in result.stdout
    assert "idea-002" not in result.stdout


def test_ideas_add(research_dir):
    """Mutation commands are disabled because idea_pool is a projection."""
    result = runner.invoke(app, ["ideas", "add", "Try dropout 0.3"])
    assert result.exit_code == 1
    assert "read-only projected backlog" in _combined_output(result)
    data = json.loads((research_dir / "idea_pool.json").read_text())
    assert data["ideas"] == []


def test_ideas_add_with_options(research_dir):
    """Mutation commands stay disabled even when options are provided."""
    result = runner.invoke(app, ["ideas", "add", "New loss function", "--category", "loss", "--priority", "2"])
    assert result.exit_code == 1
    assert "read-only projected backlog" in _combined_output(result)


def test_ideas_delete(research_dir):
    """Delete is blocked for projected backlog rows."""
    pool_path = research_dir / "idea_pool.json"
    pool_path.write_text(
        json.dumps(
            {
                "ideas": [
                    {
                        "id": "idea-001",
                        "description": "To be deleted",
                        "status": "pending",
                        "priority": 1,
                        "category": "general",
                        "source": "user",
                        "gpu_hint": "auto",
                        "claimed_by": None,
                        "assigned_experiment": None,
                        "result": None,
                        "created_at": "2026-01-01T00:00:00+00:00",
                    }
                ]
            }
        )
    )
    result = runner.invoke(app, ["ideas", "delete", "idea-001"])
    assert result.exit_code == 1
    assert "read-only projected backlog" in _combined_output(result)

    data = json.loads(pool_path.read_text())
    assert len(data["ideas"]) == 1


def test_ideas_prioritize(research_dir):
    """Prioritize is blocked for projected backlog rows."""
    pool_path = research_dir / "idea_pool.json"
    pool_path.write_text(
        json.dumps(
            {
                "ideas": [
                    {
                        "id": "idea-001",
                        "description": "An idea",
                        "status": "pending",
                        "priority": 5,
                        "category": "general",
                        "source": "user",
                        "gpu_hint": "auto",
                        "claimed_by": None,
                        "assigned_experiment": None,
                        "result": None,
                        "created_at": "2026-01-01T00:00:00+00:00",
                    }
                ]
            }
        )
    )
    result = runner.invoke(app, ["ideas", "prioritize", "idea-001", "1"])
    assert result.exit_code == 1
    assert "read-only projected backlog" in _combined_output(result)

    data = json.loads(pool_path.read_text())
    assert data["ideas"][0]["priority"] == 5


def test_ideas_list_empty(research_dir):
    """List command with empty pool shows table header but no rows."""
    result = runner.invoke(app, ["ideas", "list"])
    assert result.exit_code == 0
    assert "Projected Backlog" in result.stdout


def test_ideas_mutation_rejects_unsupported_protocol(tmp_path, monkeypatch):
    research = tmp_path / ".research"
    research.mkdir()
    (research / "idea_pool.json").write_text(json.dumps({"ideas": []}))
    (research / "config.yaml").write_text("research:\n  protocol: totally-wrong\n")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["ideas", "add", "broken"])

    assert result.exit_code == 1
    assert "Unsupported research.protocol" in _combined_output(result)
