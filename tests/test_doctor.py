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
        yaml.dump({"mode": "autonomous", "metrics": {"primary": {"name": "acc", "direction": "maximize"}}})
    )
    (research / "results.tsv").write_text("timestamp\tcommit\tmetric\n")
    (research / "idea_pool.json").write_text(json.dumps({"ideas": []}))
    (research / "activity.json").write_text("{}")
    return tmp_path


def test_doctor_valid_repo(valid_repo):
    """All file-based checks pass in a properly set-up repo."""
    checks = run_doctor(valid_repo)
    check_map = {c["check"]: c["status"] for c in checks}
    assert check_map["Git repository"] == "OK"
    assert check_map[".research/ directory"] == "OK"
    assert check_map["config.yaml"] == "OK"
    assert check_map["results.tsv"] == "OK"
    assert check_map["idea_pool.json"] == "OK"
    assert check_map["activity.json"] == "OK"
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
    assert check_map["results.tsv"] == "WARN"
    assert check_map["idea_pool.json"] == "WARN"
    assert check_map["activity.json"] == "WARN"


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


def test_doctor_bad_activity(valid_repo):
    """activity.json check fails when file contains invalid JSON."""
    (valid_repo / ".research" / "activity.json").write_text("not json")
    checks = run_doctor(valid_repo)
    check_map = {c["check"]: c["status"] for c in checks}
    assert check_map["activity.json"] == "FAIL"


def test_doctor_returns_all_checks(valid_repo):
    """Doctor should return exactly 8 checks."""
    checks = run_doctor(valid_repo)
    assert len(checks) == 8
    names = [c["check"] for c in checks]
    assert "Git repository" in names
    assert ".research/ directory" in names
    assert "config.yaml" in names
    assert "results.tsv" in names
    assert "idea_pool.json" in names
    assert "activity.json" in names
    assert "Agent binaries" in names
    assert "Python >= 3.10" in names
