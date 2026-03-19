"""Tests for graph-protocol artifact management."""

import json
import os
from pathlib import Path

from open_researcher.graph_protocol import ensure_graph_protocol_artifacts


def test_ensure_graph_protocol_artifacts_refreshes_internal_role_programs(tmp_path: Path) -> None:
    research = tmp_path / ".research"
    internal = research / ".internal" / "role_programs"
    internal.mkdir(parents=True)
    stale = internal / "manager.md"
    stale.write_text("old manager template\n", encoding="utf-8")

    ensure_graph_protocol_artifacts(research)

    content = stale.read_text(encoding="utf-8")
    assert "evaluation-contract hygiene" in content
    assert "old manager template" not in content


def test_ensure_graph_protocol_artifacts_refreshes_runtime_scripts(tmp_path: Path) -> None:
    research = tmp_path / ".research"
    scripts = research / "scripts"
    scripts.mkdir(parents=True)
    stale = scripts / "record.py"
    stale.write_text("# stale script\n", encoding="utf-8")

    ensure_graph_protocol_artifacts(research)

    content = stale.read_text(encoding="utf-8")
    assert "OPEN_RESEARCHER_RESEARCH_DIR" in content
    assert "# stale script" not in content


def test_ensure_graph_protocol_artifacts_backfills_runtime_scaffold(tmp_path: Path) -> None:
    research = tmp_path / ".research"

    ensure_graph_protocol_artifacts(research)

    assert (research / "config.yaml").exists()
    assert (research / "project-understanding.md").exists()
    assert (research / "evaluation.md").exists()
    assert (research / "literature.md").exists()
    assert (research / "ideas.md").exists()
    assert (research / "research-strategy.md").exists()
    assert (research / "results.tsv").exists()
    assert (research / "final_results.tsv").exists()
    assert (research / "idea_pool.json").exists()
    assert (research / "activity.json").exists()
    assert (research / "control.json").exists()
    assert (research / "events.jsonl").exists()
    assert (research / "experiment_progress.json").exists()
    assert (research / "gpu_status.json").exists()
    assert (research / "worktrees").is_dir()
    assert (research / "scripts" / "record.py").exists()
    assert (research / "scripts" / "rollback.sh").exists()
    assert (research / "scripts" / "launch_detached.py").exists()
    assert os.access(research / "scripts" / "rollback.sh", os.X_OK)

    assert "timestamp\tcommit\tprimary_metric" in (research / "results.tsv").read_text(encoding="utf-8")
    assert "raw_status\tfinal_status" in (research / "final_results.tsv").read_text(encoding="utf-8")
    assert json.loads((research / "idea_pool.json").read_text(encoding="utf-8")) == {"ideas": []}
    assert json.loads((research / "activity.json").read_text(encoding="utf-8")) == {}
    assert json.loads((research / "experiment_progress.json").read_text(encoding="utf-8")) == {"phase": "init"}
    assert json.loads((research / "gpu_status.json").read_text(encoding="utf-8")) == {"gpus": []}

    control = json.loads((research / "control.json").read_text(encoding="utf-8"))
    assert control["paused"] is False
    assert control["skip_current"] is False
    assert control["control_seq"] == 0
    assert control["applied_command_ids"] == []
    assert control["event_count"] == 0


def test_ensure_graph_protocol_artifacts_preserves_existing_results_file(tmp_path: Path) -> None:
    research = tmp_path / ".research"
    research.mkdir(parents=True)
    results = research / "results.tsv"
    results.write_text("custom-results\n", encoding="utf-8")

    ensure_graph_protocol_artifacts(research)

    assert results.read_text(encoding="utf-8") == "custom-results\n"
