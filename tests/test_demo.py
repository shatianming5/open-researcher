"""Tests for the demo command."""

import json
import subprocess
import tempfile
from pathlib import Path

from open_researcher.demo_cmd import _build_idea_pool, _build_results_tsv, _populate_research


def test_build_results_tsv():
    """Results TSV has correct structure."""
    from datetime import datetime, timezone

    tsv = _build_results_tsv(datetime.now(timezone.utc))
    lines = tsv.strip().split("\n")
    assert lines[0].startswith("timestamp\t")
    # 15 experiments + header
    assert len(lines) == 16
    # Check columns
    for line in lines[1:]:
        parts = line.split("\t")
        assert len(parts) == 7


def test_build_idea_pool():
    """Idea pool has correct structure."""
    pool = _build_idea_pool()
    assert "ideas" in pool
    assert len(pool["ideas"]) == 8
    statuses = {i["status"] for i in pool["ideas"]}
    assert "pending" in statuses
    assert "done" in statuses
    assert "running" in statuses
    for idea in pool["ideas"]:
        assert "assigned_experiment" not in idea
        assert "claimed_by" not in idea


def test_populate_research():
    """All expected files are created in .research/."""
    with tempfile.TemporaryDirectory() as tmp:
        research = Path(tmp) / ".research"
        research.mkdir()
        _populate_research(research)

        assert (research / "results.tsv").exists()
        assert (research / "idea_pool.json").exists()
        assert (research / "activity.json").exists()
        assert (research / "config.yaml").exists()
        assert (research / "control.json").exists()
        assert (research / "events.jsonl").exists()
        assert (research / "project-understanding.md").exists()
        assert (research / "literature.md").exists()
        assert (research / "evaluation.md").exists()
        assert (research / "gpu_status.json").exists()
        assert (research / "scripts").is_dir()

        # Validate JSON files parse correctly
        json.loads((research / "idea_pool.json").read_text())
        json.loads((research / "activity.json").read_text())
        json.loads((research / "control.json").read_text())
        json.loads((research / "gpu_status.json").read_text())
        assert (research / "events.jsonl").read_text() == ""


def test_demo_cli_help():
    """Demo command is registered and shows in help."""
    result = subprocess.run(
        ["python3", "-m", "open_researcher.cli", "--help"],
        capture_output=True,
        text=True,
    )
    assert "demo" in result.stdout
