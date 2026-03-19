"""Tests for deterministic benchmark smoke execution."""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

from open_researcher.benchmark_smoke import run_benchmark_smoke


def test_run_benchmark_smoke_records_metric(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)

    research = repo / ".research"
    research.mkdir()
    (repo / "train.py").write_text("print('score 1.5')\n", encoding="utf-8")
    (research / "config.yaml").write_text(
        "\n".join(
            [
                "mode: autonomous",
                "experiment:",
                "  timeout: 30",
                "metrics:",
                "  primary:",
                "    name: score",
                "    direction: higher_is_better",
                "bootstrap:",
                f'  python: "{sys.executable}"',
                f'  smoke_command: "{sys.executable} train.py"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = run_benchmark_smoke(repo, description="smoke baseline")

    assert summary["metric_name"] == "score"
    assert summary["metric_value"] == 1.5
    assert (research / "scripts" / "record.py").exists()
    assert (research / "results.tsv").exists()
    assert (research / "final_results.tsv").exists()

    with (research / "results.tsv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert len(rows) == 1
    assert rows[0]["primary_metric"] == "score"
    assert rows[0]["metric_value"] == "1.500000"
    assert rows[0]["status"] == "keep"
    assert rows[0]["description"] == "smoke baseline"
