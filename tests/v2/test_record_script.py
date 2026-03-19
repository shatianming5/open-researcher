"""Tests for the record.py helper script."""

from __future__ import annotations

import csv
import os
import sys
import threading
from pathlib import Path

import pytest

# Import the script's main function directly
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "open_researcher_v2" / "skills" / "scripts"))
from record import main as record_main, _find_research_dir  # noqa: E402


class TestRecordScript:
    """Test record.py creates and appends to results.tsv."""

    def test_creates_tsv_with_header(self, tmp_path, monkeypatch):
        """First invocation creates the file with a header row."""
        rd = tmp_path / ".research"
        rd.mkdir()
        monkeypatch.chdir(tmp_path)

        record_main(["--frontier-id", "f-001", "--status", "keep",
                      "--metric", "accuracy", "--value", "0.95"])

        tsv = rd / "results.tsv"
        assert tsv.exists()
        rows = list(csv.DictReader(open(tsv, encoding="utf-8"), delimiter="\t"))
        assert len(rows) == 1
        assert rows[0]["frontier_id"] == "f-001"
        assert rows[0]["status"] == "keep"
        assert rows[0]["value"] == "0.95"

    def test_appends_without_duplicate_header(self, tmp_path, monkeypatch):
        """Second invocation appends a row, no duplicate header."""
        rd = tmp_path / ".research"
        rd.mkdir()
        monkeypatch.chdir(tmp_path)

        record_main(["--frontier-id", "f-001", "--status", "keep",
                      "--metric", "acc", "--value", "0.90"])
        record_main(["--frontier-id", "f-002", "--status", "discard",
                      "--metric", "acc", "--value", "0.80"])

        tsv = rd / "results.tsv"
        content = tsv.read_text(encoding="utf-8")
        # Only one header line
        assert content.count("frontier_id") == 1

        rows = list(csv.DictReader(open(tsv, encoding="utf-8"), delimiter="\t"))
        assert len(rows) == 2
        assert rows[1]["frontier_id"] == "f-002"
        assert rows[1]["status"] == "discard"

    def test_concurrent_writes(self, tmp_path, monkeypatch):
        """Multiple concurrent writes don't corrupt the file."""
        rd = tmp_path / ".research"
        rd.mkdir()
        monkeypatch.chdir(tmp_path)

        errors = []

        def _write(i):
            try:
                record_main(["--frontier-id", f"f-{i:03d}", "--status", "keep",
                              "--metric", "acc", "--value", f"0.{i:02d}"])
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_write, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        tsv = rd / "results.tsv"
        rows = list(csv.DictReader(open(tsv, encoding="utf-8"), delimiter="\t"))
        assert len(rows) == 10

    def test_finds_research_dir_in_parent(self, tmp_path, monkeypatch):
        """record.py walks up to find .research in parent directories."""
        rd = tmp_path / ".research"
        rd.mkdir()
        child = tmp_path / "subdir" / "deep"
        child.mkdir(parents=True)
        monkeypatch.chdir(child)

        record_main(["--frontier-id", "f-001", "--status", "keep",
                      "--value", "0.88"])

        tsv = rd / "results.tsv"
        assert tsv.exists()

    def test_optional_fields(self, tmp_path, monkeypatch):
        """Optional fields default to empty strings."""
        rd = tmp_path / ".research"
        rd.mkdir()
        monkeypatch.chdir(tmp_path)

        record_main(["--frontier-id", "f-001", "--status", "error"])

        tsv = rd / "results.tsv"
        rows = list(csv.DictReader(open(tsv, encoding="utf-8"), delimiter="\t"))
        assert rows[0]["metric"] == ""
        assert rows[0]["value"] == ""
        assert rows[0]["description"] == ""

    def test_crash_status(self, tmp_path, monkeypatch):
        """crash is a valid status."""
        rd = tmp_path / ".research"
        rd.mkdir()
        monkeypatch.chdir(tmp_path)

        record_main(["--frontier-id", "f-001", "--status", "crash",
                      "--desc", "OOM during training"])

        tsv = rd / "results.tsv"
        rows = list(csv.DictReader(open(tsv, encoding="utf-8"), delimiter="\t"))
        assert rows[0]["status"] == "crash"
        assert rows[0]["description"] == "OOM during training"

    def test_invalid_status_rejected(self, tmp_path, monkeypatch):
        """Invalid status values are rejected by argparse."""
        rd = tmp_path / ".research"
        rd.mkdir()
        monkeypatch.chdir(tmp_path)

        with pytest.raises(SystemExit):
            record_main(["--frontier-id", "f-001", "--status", "invalid_status"])

    def test_timestamp_is_set(self, tmp_path, monkeypatch):
        """Timestamp is automatically set."""
        rd = tmp_path / ".research"
        rd.mkdir()
        monkeypatch.chdir(tmp_path)

        record_main(["--frontier-id", "f-001", "--status", "keep", "--value", "0.9"])

        tsv = rd / "results.tsv"
        rows = list(csv.DictReader(open(tsv, encoding="utf-8"), delimiter="\t"))
        assert rows[0]["timestamp"] != ""
        assert "T" in rows[0]["timestamp"]  # ISO format
