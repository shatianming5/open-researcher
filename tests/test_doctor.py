"""Tests for the doctor health-check command."""

import json
import shutil
import subprocess

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
    (research / "scout_program.md").write_text("# scout_program.md\n")
    internal = research / ".internal" / "role_programs"
    internal.mkdir(parents=True, exist_ok=True)
    for name in ["manager.md", "critic.md", "experiment.md"]:
        (internal / name).write_text(f"# {name}\n")
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
    assert len(checks) == 20
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
    assert "OpenCode CLI" in names
    assert "GPU driver" in names
    assert "GPU devices" in names
    assert "Python >= 3.10" in names


def test_doctor_reports_opencode_run_capability(valid_repo, monkeypatch):
    import open_researcher.doctor_cmd as doctor_cmd

    def fake_which(binary: str) -> str | None:
        return f"/usr/bin/{binary}"

    class Result:
        def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(cmd, **kwargs):
        if cmd == ["opencode", "--version"]:
            return Result(0, stdout="1.1.48\n")
        if cmd == ["opencode", "run", "--help"]:
            return Result(0, stdout="opencode run [message..]\n")
        if cmd[0] == "nvidia-smi":
            return Result(0, stdout="535.00\n")
        raise AssertionError(f"Unexpected subprocess call: {cmd}")

    monkeypatch.setattr(doctor_cmd.shutil, "which", fake_which)
    monkeypatch.setattr(doctor_cmd.subprocess, "run", fake_run)

    checks = run_doctor(valid_repo)
    check_map = {c["check"]: c for c in checks}
    assert check_map["OpenCode CLI"]["status"] == "OK"
    assert "1.1.48" in check_map["OpenCode CLI"]["detail"]
    assert "`run` subcommand available" in check_map["OpenCode CLI"]["detail"]


def test_doctor_gpu_with_nvidia_smi(valid_repo, monkeypatch):
    """GPU checks report OK when nvidia-smi is available and returns GPU data."""
    import open_researcher.doctor_cmd as doctor_cmd

    original_which = shutil.which

    def fake_which(binary: str) -> str | None:
        if binary == "nvidia-smi":
            return "/usr/bin/nvidia-smi"
        return original_which(binary)

    class Result:
        def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    original_run = subprocess.run

    def fake_run(cmd, **kwargs):
        if cmd[0] == "nvidia-smi":
            if "--query-gpu=driver_version" in cmd[1]:
                return Result(0, stdout="535.129.03\n")
            if "--query-gpu=index,name,memory.total,memory.free,utilization.gpu" in cmd[1]:
                return Result(
                    0,
                    stdout=(
                        "0, NVIDIA A100-SXM4-80GB, 81920, 79000, 12\n"
                        "1, NVIDIA A100-SXM4-80GB, 81920, 75000, 35\n"
                    ),
                )
        return original_run(cmd, **kwargs)

    monkeypatch.setattr(doctor_cmd.shutil, "which", fake_which)
    monkeypatch.setattr(doctor_cmd.subprocess, "run", fake_run)

    checks = run_doctor(valid_repo)
    check_map = {c["check"]: c for c in checks}
    assert check_map["GPU driver"]["status"] == "OK"
    assert "535.129.03" in check_map["GPU driver"]["detail"]
    assert check_map["GPU devices"]["status"] == "OK"
    assert "2 GPU(s)" in check_map["GPU devices"]["detail"]
    assert "A100" in check_map["GPU devices"]["detail"]


def test_doctor_gpu_no_nvidia_smi(valid_repo, monkeypatch):
    """GPU checks return WARN when nvidia-smi is not installed."""
    import open_researcher.doctor_cmd as doctor_cmd

    original_which = shutil.which

    def fake_which(binary: str) -> str | None:
        if binary == "nvidia-smi":
            return None
        return original_which(binary)

    monkeypatch.setattr(doctor_cmd.shutil, "which", fake_which)

    checks = run_doctor(valid_repo)
    check_map = {c["check"]: c for c in checks}
    assert check_map["GPU driver"]["status"] == "WARN"
    assert "not found" in check_map["GPU driver"]["detail"]
    assert check_map["GPU devices"]["status"] == "WARN"


def test_doctor_gpu_nvidia_smi_fails(valid_repo, monkeypatch):
    """GPU checks return WARN when nvidia-smi is present but returns non-zero."""
    import open_researcher.doctor_cmd as doctor_cmd

    original_which = shutil.which

    def fake_which(binary: str) -> str | None:
        if binary == "nvidia-smi":
            return "/usr/bin/nvidia-smi"
        return original_which(binary)

    class Result:
        def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    original_run = subprocess.run

    def fake_run(cmd, **kwargs):
        if cmd[0] == "nvidia-smi":
            return Result(1, stderr="NVIDIA-SMI has failed")
        return original_run(cmd, **kwargs)

    monkeypatch.setattr(doctor_cmd.shutil, "which", fake_which)
    monkeypatch.setattr(doctor_cmd.subprocess, "run", fake_run)

    checks = run_doctor(valid_repo)
    check_map = {c["check"]: c for c in checks}
    assert check_map["GPU driver"]["status"] == "WARN"
    assert "failed" in check_map["GPU driver"]["detail"]
    assert check_map["GPU devices"]["status"] == "WARN"
