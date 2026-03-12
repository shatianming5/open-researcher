import tempfile
from pathlib import Path

from paperfarm.export_cmd import do_export, generate_report


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


def test_generate_report_missing_config(tmp_path):
    """generate_report should use defaults when config.yaml is missing."""
    research = tmp_path / ".research"
    research.mkdir()
    (research / "results.tsv").write_text(
        "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
        "2026-03-08T10:00:00\ta1b2c3d\taccuracy\t0.850000\t{}\tkeep\tbaseline\n"
    )
    # No config.yaml — should not crash, should use "unknown" as metric name
    report = generate_report(tmp_path)
    assert "# Experiment Report" in report
    assert "unknown" in report


def test_do_export_to_file(tmp_path):
    """do_export should write to file when output parameter is provided."""
    research = tmp_path / ".research"
    research.mkdir()
    (research / "config.yaml").write_text(
        "mode: autonomous\nmetrics:\n  primary:\n    name: accuracy\n    direction: higher_is_better\n"
    )
    (research / "results.tsv").write_text(
        "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
        "2026-03-08T10:00:00\ta1b2c3d\taccuracy\t0.850000\t{}\tkeep\tbaseline\n"
    )
    output_file = tmp_path / "report.md"
    do_export(tmp_path, output=output_file)
    assert output_file.exists()
    content = output_file.read_text()
    assert "# Experiment Report" in content
    assert "accuracy" in content


def test_do_export_to_stdout(tmp_path, capsys):
    """do_export should print to stdout when no output parameter."""
    research = tmp_path / ".research"
    research.mkdir()
    (research / "config.yaml").write_text(
        "mode: autonomous\nmetrics:\n  primary:\n    name: accuracy\n    direction: higher_is_better\n"
    )
    (research / "results.tsv").write_text(
        "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
    )
    do_export(tmp_path)
    captured = capsys.readouterr()
    assert "# Experiment Report" in captured.out
