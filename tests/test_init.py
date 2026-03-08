import os
import subprocess
import sys
import tempfile
from pathlib import Path

from open_researcher.init_cmd import do_init


def test_init_creates_research_directory():
    """init should create .research/ with all expected files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=tmpdir, capture_output=True)

        do_init(repo_path=Path(tmpdir), tag="test1")

        research = Path(tmpdir, ".research")
        assert research.is_dir()
        assert (research / "program.md").is_file()
        assert (research / "config.yaml").is_file()
        assert (research / "project-understanding.md").is_file()
        assert (research / "evaluation.md").is_file()
        assert (research / "results.tsv").is_file()
        assert (research / "scripts" / "record.py").is_file()
        assert (research / "scripts" / "rollback.sh").is_file()

        # Check tag substitution in program.md
        program = (research / "program.md").read_text()
        assert "test1" in program

        # Check results.tsv has header
        results = (research / "results.tsv").read_text()
        assert results.startswith("timestamp\t")

        # Check rollback.sh is executable
        assert os.access(research / "scripts" / "rollback.sh", os.X_OK)


def test_init_refuses_if_research_exists():
    """init should refuse if .research/ already exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        Path(tmpdir, ".research").mkdir()

        try:
            do_init(repo_path=Path(tmpdir), tag="test2")
            assert False, "Should have raised"
        except SystemExit:
            pass


def test_init_generates_default_tag():
    """init without tag should use today's date."""
    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=tmpdir, capture_output=True)

        do_init(repo_path=Path(tmpdir), tag=None)

        program = (Path(tmpdir) / ".research" / "program.md").read_text()
        assert "research/" in program
