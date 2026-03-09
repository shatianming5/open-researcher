"""Tests for the ideas CLI subcommand."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from open_researcher.cli import app

runner = CliRunner()


@pytest.fixture
def research_dir(tmp_path, monkeypatch):
    """Set up a minimal .research directory with an empty idea pool."""
    research = tmp_path / ".research"
    research.mkdir()
    (research / "idea_pool.json").write_text(json.dumps({"ideas": []}))
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
    """Add command creates a new idea in the pool."""
    result = runner.invoke(app, ["ideas", "add", "Try dropout 0.3"])
    assert result.exit_code == 0
    assert "Added: idea-001" in result.stdout

    data = json.loads((research_dir / "idea_pool.json").read_text())
    assert len(data["ideas"]) == 1
    assert data["ideas"][0]["description"] == "Try dropout 0.3"
    assert data["ideas"][0]["source"] == "user"


def test_ideas_add_with_options(research_dir):
    """Add command with category and priority."""
    result = runner.invoke(
        app, ["ideas", "add", "New loss function", "--category", "loss", "--priority", "2"]
    )
    assert result.exit_code == 0

    data = json.loads((research_dir / "idea_pool.json").read_text())
    idea = data["ideas"][0]
    assert idea["category"] == "loss"
    assert idea["priority"] == 2


def test_ideas_delete(research_dir):
    """Delete command removes an idea from the pool."""
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
    assert result.exit_code == 0
    assert "Deleted: idea-001" in result.stdout

    data = json.loads(pool_path.read_text())
    assert len(data["ideas"]) == 0


def test_ideas_prioritize(research_dir):
    """Prioritize command updates an idea's priority."""
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
    assert result.exit_code == 0
    assert "Updated idea-001 priority to 1" in result.stdout

    data = json.loads(pool_path.read_text())
    assert data["ideas"][0]["priority"] == 1


def test_ideas_list_empty(research_dir):
    """List command with empty pool shows table header but no rows."""
    result = runner.invoke(app, ["ideas", "list"])
    assert result.exit_code == 0
    assert "Ideas" in result.stdout
