import tempfile
from pathlib import Path

from open_researcher.results_cmd import load_results


def test_load_results():
    with tempfile.TemporaryDirectory() as tmpdir:
        research = Path(tmpdir, ".research")
        research.mkdir()
        (research / "results.tsv").write_text(
            "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
            "2026-03-08T10:00:00\ta1b2c3d\taccuracy\t0.850000\t{}\tkeep\tbaseline\n"
        )
        rows = load_results(Path(tmpdir))
        assert len(rows) == 1
        assert rows[0]["status"] == "keep"


def test_load_results_empty():
    with tempfile.TemporaryDirectory() as tmpdir:
        research = Path(tmpdir, ".research")
        research.mkdir()
        (research / "results.tsv").write_text(
            "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
        )
        rows = load_results(Path(tmpdir))
        assert len(rows) == 0
