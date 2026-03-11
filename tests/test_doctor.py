"""Tests for the doctor health-check command."""

import json

import pytest
import yaml

from open_researcher.doctor_cmd import run_doctor


@pytest.fixture
def valid_repo(tmp_path):
    """Create a minimal valid research repo structure."""
    (tmp_path / ".git").mkdir()
    research = tmp_path / ".research"
    research.mkdir()
    (research / "config.yaml").write_text(
        yaml.dump(
            {
                "mode": "autonomous",
                "bootstrap": {"auto_prepare": False},
                "metrics": {"primary": {"name": "acc", "direction": "maximize"}},
            }
        )
    )
    (research / "results.tsv").write_text("timestamp\tcommit\tmetric\n")
    (research / "research_graph.json").write_text(
        json.dumps(
            {
                "version": "research-v1",
                "repo_profile": {},
                "hypotheses": [],
                "experiment_specs": [],
                "evidence": [],
                "claim_updates": [],
                "branch_relations": [],
                "frontier": [],
                "counters": {},
            }
        )
    )
    (research / "research_memory.json").write_text(
        json.dumps(
            {
                "version": "research-v1",
                "repo_type_priors": [],
                "ideation_memory": [],
                "experiment_memory": [],
            }
        )
    )
    (research / "idea_pool.json").write_text(json.dumps({"ideas": []}))
    (research / "activity.json").write_text("{}")
    (research / "events.jsonl").write_text("")
    (research / "experiment_progress.json").write_text(json.dumps({"phase": "init"}))
    (research / "bootstrap_state.json").write_text(
        json.dumps(
            {
                "version": "research-v1",
                "status": "disabled",
                "repo_profile": {"kind": "python", "python_project": True, "manifests": []},
                "working_dir": ".",
                "python_env": {"executable": "", "source": ""},
                "install": {},
                "data": {},
                "smoke": {},
                "errors": [],
                "unresolved": [],
            }
        )
    )
    for name in ["scout_program.md", "manager_program.md", "critic_program.md", "experiment_program.md"]:
        (research / name).write_text(f"# {name}\n")
    return tmp_path


def test_doctor_valid_repo(valid_repo):
    """All file-based checks pass in a properly set-up repo."""
    checks = run_doctor(valid_repo)
    check_map = {c["check"]: c["status"] for c in checks}
    assert check_map["Git repository"] == "OK"
    assert check_map[".research/ directory"] == "OK"
    assert check_map["config.yaml"] == "OK"
    assert check_map["research.protocol"] == "OK"
    assert check_map["results.tsv"] == "OK"
    assert check_map["research_graph.json"] == "OK"
    assert check_map["research_memory.json"] == "OK"
    assert check_map["idea_pool.json"] == "OK"
    assert check_map["activity.json"] == "OK"
    assert check_map["role programs"] == "OK"
    assert check_map["experiment_progress.json"] == "OK"
    assert check_map["events.jsonl"] == "OK"
    assert check_map["Python >= 3.10"] == "OK"


def test_doctor_no_git(valid_repo):
    """Git check fails when .git is missing."""
    import shutil

    shutil.rmtree(valid_repo / ".git")
    checks = run_doctor(valid_repo)
    check_map = {c["check"]: c["status"] for c in checks}
    assert check_map["Git repository"] == "FAIL"


def test_doctor_no_research(tmp_path):
    """.research check fails when directory is missing."""
    (tmp_path / ".git").mkdir()
    checks = run_doctor(tmp_path)
    check_map = {c["check"]: c["status"] for c in checks}
    assert check_map[".research/ directory"] == "FAIL"
    # All file-based checks should be WARN when .research doesn't exist
    assert check_map["config.yaml"] == "WARN"
    assert check_map["research.protocol"] == "OK"
    assert check_map["results.tsv"] == "WARN"
    assert check_map["research_graph.json"] == "WARN"
    assert check_map["research_memory.json"] == "WARN"
    assert check_map["idea_pool.json"] == "WARN"
    assert check_map["activity.json"] == "WARN"
    assert check_map["role programs"] == "FAIL"
    assert check_map["experiment_progress.json"] == "WARN"
    assert check_map["events.jsonl"] == "WARN"


def test_doctor_bad_config(valid_repo):
    """config.yaml check fails when file contains bad YAML."""
    (valid_repo / ".research" / "config.yaml").write_text(": :\n  bad: [yaml: broken")
    checks = run_doctor(valid_repo)
    check_map = {c["check"]: c["status"] for c in checks}
    assert check_map["config.yaml"] == "FAIL"


def test_doctor_bad_idea_pool(valid_repo):
    """idea_pool.json check fails when file contains invalid JSON."""
    (valid_repo / ".research" / "idea_pool.json").write_text("{not json")
    checks = run_doctor(valid_repo)
    check_map = {c["check"]: c["status"] for c in checks}
    assert check_map["idea_pool.json"] == "FAIL"


def test_doctor_invalid_protocol(valid_repo):
    (valid_repo / ".research" / "config.yaml").write_text(yaml.dump({"research": {"protocol": "totally-wrong"}}))
    checks = run_doctor(valid_repo)
    check_map = {c["check"]: c["status"] for c in checks}
    assert check_map["research.protocol"] == "FAIL"


def test_doctor_bad_activity(valid_repo):
    """activity.json check fails when file contains invalid JSON."""
    (valid_repo / ".research" / "activity.json").write_text("not json")
    checks = run_doctor(valid_repo)
    check_map = {c["check"]: c["status"] for c in checks}
    assert check_map["activity.json"] == "FAIL"


def test_doctor_wrong_shaped_graph_fails_instead_of_crashing(valid_repo):
    (valid_repo / ".research" / "research_graph.json").write_text(json.dumps({"frontier": {}}))
    checks = run_doctor(valid_repo)
    check_map = {c["check"]: c["status"] for c in checks}
    assert check_map["research_graph.json"] == "FAIL"


def test_doctor_events_require_monotonic_positive_seq(valid_repo):
    (valid_repo / ".research" / "events.jsonl").write_text(
        json.dumps({"seq": 2, "event": "first"}) + "\n" + json.dumps({"event": "missing-seq"}) + "\n"
    )
    checks = run_doctor(valid_repo)
    check_map = {c["check"]: c["status"] for c in checks}
    assert check_map["events.jsonl"] == "FAIL"


def test_doctor_returns_all_checks(valid_repo):
    """Doctor should return the expanded research-v1 health surface."""
    checks = run_doctor(valid_repo)
    assert len(checks) == 17
    names = [c["check"] for c in checks]
    assert "Git repository" in names
    assert ".research/ directory" in names
    assert "config.yaml" in names
    assert "research.protocol" in names
    assert "results.tsv" in names
    assert "research_graph.json" in names
    assert "research_memory.json" in names
    assert "idea_pool.json" in names
    assert "activity.json" in names
    assert "role programs" in names
    assert "experiment_progress.json" in names
    assert "bootstrap_state.json" in names
    assert "bootstrap resolution" in names
    assert "bootstrap expected paths" in names
    assert "events.jsonl" in names
    assert "Agent binaries" in names
    assert "Python >= 3.10" in names
