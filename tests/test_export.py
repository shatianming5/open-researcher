import tempfile
from pathlib import Path

from open_researcher.export_cmd import generate_report


def test_generate_report():
    with tempfile.TemporaryDirectory() as tmpdir:
        research = Path(tmpdir, ".research")
        research.mkdir()
        (research / "config.yaml").write_text(
            "mode: autonomous\nmetrics:\n  primary:\n    name: accuracy\n    direction: higher_is_better\n"
        )
        (research / "results.tsv").write_text(
            "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
            "2026-03-08T10:00:00\ta1b2c3d\taccuracy\t0.850000\t{}\tkeep\tbaseline\n"
            "2026-03-08T10:15:00\tb2c3d4e\taccuracy\t0.870000\t{}\tkeep\tincrease LR\n"
        )

        report = generate_report(Path(tmpdir))
        assert "# Experiment Report" in report
        assert "accuracy" in report
        assert "baseline" in report
        assert "0.870000" in report
