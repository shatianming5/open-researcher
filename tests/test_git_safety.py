"""Tests for git runtime safety helpers."""

import subprocess
import tempfile
from pathlib import Path

from paperfarm.git_safety import capture_clean_workspace_snapshot, rollback_workspace


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(path), capture_output=True, check=True)
    (path / "hello.py").write_text("print('hello')\n", encoding="utf-8")
    subprocess.run(["git", "add", "hello.py"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=str(path), capture_output=True, check=True)


def test_capture_and_rollback_preserve_runtime_state_but_clean_code_changes():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _init_git_repo(repo)
        research = repo / ".research"
        research.mkdir()
        (research / "results.tsv").write_text("header\n", encoding="utf-8")

        snapshot = capture_clean_workspace_snapshot(repo)

        (repo / "hello.py").write_text("print('mutated')\n", encoding="utf-8")
        (repo / "scratch.txt").write_text("temp\n", encoding="utf-8")

        rollback_workspace(repo, snapshot)

        assert (repo / "hello.py").read_text(encoding="utf-8") == "print('hello')\n"
        assert not (repo / "scratch.txt").exists()
        assert (research / "results.tsv").exists()
