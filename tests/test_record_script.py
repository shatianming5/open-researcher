"""Tests for the record.py helper script."""
from __future__ import annotations

import csv
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

# Import directly for unit-level tests
RECORD_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "paperfarm"
    / "skills"
    / "scripts"
    / "record.py"
)


@pytest.fixture()
def research_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a .research dir and cd into tmp_path."""
    rd = tmp_path / ".research"
    rd.mkdir()
    monkeypatch.chdir(tmp_path)
    return rd


class TestRecordScript:
    """Tests for record.py as a subprocess."""

    def test_creates_results_tsv_with_header(
        self, research_dir: Path
    ) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(RECORD_SCRIPT),
                "--frontier-id",
                "F-1",
                "--status",
                "keep",
                "--value",
                "0.87",
            ],
            cwd=research_dir.parent,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "Recorded: F-1" in result.stdout

        tsv = research_dir / "results.tsv"
        assert tsv.exists()
        rows = list(csv.DictReader(tsv.open(), delimiter="\t"))
        assert len(rows) == 1
        assert rows[0]["frontier_id"] == "F-1"
        assert rows[0]["status"] == "keep"
        assert rows[0]["value"] == "0.87"

    def test_appends_rows(self, research_dir: Path) -> None:
        for i, status in enumerate(["keep", "discard"]):
            subprocess.run(
                [
                    sys.executable,
                    str(RECORD_SCRIPT),
                    "--frontier-id",
                    f"F-{i}",
                    "--status",
                    status,
                ],
                cwd=research_dir.parent,
                capture_output=True,
                text=True,
                check=True,
            )
        tsv = research_dir / "results.tsv"
        rows = list(csv.DictReader(tsv.open(), delimiter="\t"))
        assert len(rows) == 2
        assert rows[0]["frontier_id"] == "F-0"
        assert rows[1]["frontier_id"] == "F-1"

    def test_concurrent_writes(self, research_dir: Path) -> None:
        """Multiple concurrent invocations should not corrupt the file."""

        def _write(idx: int) -> int:
            r = subprocess.run(
                [
                    sys.executable,
                    str(RECORD_SCRIPT),
                    "--frontier-id",
                    f"F-{idx}",
                    "--status",
                    "keep",
                    "--value",
                    str(idx),
                    "--worker",
                    f"w-{idx}",
                ],
                cwd=research_dir.parent,
                capture_output=True,
                text=True,
            )
            return r.returncode

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(_write, range(8)))

        assert all(rc == 0 for rc in results)
        tsv = research_dir / "results.tsv"
        rows = list(csv.DictReader(tsv.open(), delimiter="\t"))
        assert len(rows) == 8

    def test_finds_research_in_parent(self, tmp_path: Path) -> None:
        """record.py should walk up to find .research/."""
        rd = tmp_path / ".research"
        rd.mkdir()
        subdir = tmp_path / "src" / "deep"
        subdir.mkdir(parents=True)

        result = subprocess.run(
            [
                sys.executable,
                str(RECORD_SCRIPT),
                "--frontier-id",
                "F-99",
                "--status",
                "error",
            ],
            cwd=subdir,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        tsv = rd / "results.tsv"
        assert tsv.exists()

    def test_all_fields_recorded(self, research_dir: Path) -> None:
        subprocess.run(
            [
                sys.executable,
                str(RECORD_SCRIPT),
                "--frontier-id",
                "F-5",
                "--status",
                "discard",
                "--metric",
                "accuracy",
                "--value",
                "0.42",
                "--desc",
                "baseline comparison",
                "--worker",
                "w-0",
            ],
            cwd=research_dir.parent,
            capture_output=True,
            text=True,
            check=True,
        )
        tsv = research_dir / "results.tsv"
        rows = list(csv.DictReader(tsv.open(), delimiter="\t"))
        row = rows[0]
        assert row["frontier_id"] == "F-5"
        assert row["metric"] == "accuracy"
        assert row["value"] == "0.42"
        assert row["description"] == "baseline comparison"
        assert row["worker"] == "w-0"
        assert row["timestamp"]  # non-empty

    def test_invalid_status_rejected(self, research_dir: Path) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(RECORD_SCRIPT),
                "--frontier-id",
                "F-1",
                "--status",
                "invalid",
            ],
            cwd=research_dir.parent,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
