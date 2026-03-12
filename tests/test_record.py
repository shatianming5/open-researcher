# tests/test_record.py
import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

RECORD_SCRIPT = Path(__file__).parent.parent / "src" / "paperfarm" / "scripts" / "record.py"


def test_record_appends_to_tsv():
    """record.py should append a row to results.tsv with correct fields."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Setup: create a git repo with a commit
        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True)
        Path(tmpdir, "dummy.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmpdir, capture_output=True)

        # Create .research dir and empty results.tsv with header
        research_dir = Path(tmpdir, ".research")
        research_dir.mkdir()
        results_file = research_dir / "results.tsv"
        results_file.write_text(
            "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
        )

        # Copy record.py to target
        target_script = research_dir / "scripts" / "record.py"
        target_script.parent.mkdir(parents=True, exist_ok=True)
        target_script.write_text(RECORD_SCRIPT.read_text())

        # Run record.py
        result = subprocess.run(
            [
                sys.executable,
                str(target_script),
                "--metric",
                "accuracy",
                "--value",
                "0.85",
                "--secondary",
                '{"f1": 0.83}',
                "--status",
                "keep",
                "--desc",
                "baseline",
            ],
            cwd=tmpdir,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"record.py failed: {result.stderr}"

        # Verify results.tsv
        rows = list(csv.DictReader(results_file.open(), delimiter="\t"))
        assert len(rows) == 1
        assert rows[0]["primary_metric"] == "accuracy"
        assert rows[0]["metric_value"] == "0.850000"
        assert rows[0]["status"] == "keep"
        assert rows[0]["description"] == "baseline"
        secondary = json.loads(rows[0]["secondary_metrics"])
        assert secondary["f1"] == 0.83
        assert "_open_researcher_result_id" in secondary
        assert len(rows[0]["commit"]) == 7  # short hash
        assert rows[0]["timestamp"]  # non-empty
        assert "." in rows[0]["timestamp"]


def test_record_creates_header_if_missing():
    """record.py should create results.tsv with header if file doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True)
        Path(tmpdir, "dummy.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmpdir, capture_output=True)

        research_dir = Path(tmpdir, ".research")
        research_dir.mkdir()
        scripts_dir = research_dir / "scripts"
        scripts_dir.mkdir()

        target_script = scripts_dir / "record.py"
        target_script.write_text(RECORD_SCRIPT.read_text())

        result = subprocess.run(
            [
                sys.executable,
                str(target_script),
                "--metric",
                "loss",
                "--value",
                "0.42",
                "--status",
                "keep",
                "--desc",
                "test",
            ],
            cwd=tmpdir,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

        results_file = research_dir / "results.tsv"
        assert results_file.exists()
        lines = results_file.read_text().strip().split("\n")
        assert len(lines) == 2  # header + 1 row
        assert lines[0].startswith("timestamp\t")


def test_record_auto_harvests_eval_output_metrics():
    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True)
        Path(tmpdir, "dummy.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmpdir, capture_output=True)

        research_dir = Path(tmpdir, ".research")
        research_dir.mkdir()
        (research_dir / "eval_output.log").write_text(
            "max_abs_diff=0.000000\n"
            "torch_ms=4.5055\n"
            "cpp_ms=4.2402\n"
            "speedup_ratio=1.0626\n"
            "invalid_reason=\n"
        )
        results_file = research_dir / "results.tsv"
        results_file.write_text(
            "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
        )

        target_script = research_dir / "scripts" / "record.py"
        target_script.parent.mkdir(parents=True, exist_ok=True)
        target_script.write_text(RECORD_SCRIPT.read_text())

        result = subprocess.run(
            [
                sys.executable,
                str(target_script),
                "--metric",
                "speedup_ratio",
                "--value",
                "1.0626",
                "--status",
                "keep",
                "--desc",
                "idea-001",
            ],
            cwd=tmpdir,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

        rows = list(csv.DictReader(results_file.open(), delimiter="\t"))
        secondary = json.loads(rows[0]["secondary_metrics"])
        assert secondary["max_abs_diff"] == 0.0
        assert secondary["torch_ms"] == 4.5055
        assert secondary["cpp_ms"] == 4.2402
        assert secondary["invalid_reason"] == ""
        assert "speedup_ratio" not in secondary
