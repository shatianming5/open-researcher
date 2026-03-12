import json
import tempfile
from pathlib import Path

from open_researcher.results_cmd import (
    derive_final_results,
    load_results,
    print_results,
    write_final_results_tsv,
)


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


def test_print_results_with_missing_fields(tmp_path):
    """print_results should not crash when rows have missing fields."""
    research = tmp_path / ".research"
    research.mkdir()
    # Write a TSV with only some columns (missing primary_metric, commit, etc.)
    (research / "results.tsv").write_text("status\tmetric_value\tdescription\nkeep\t0.85\tbaseline\n")
    # Should not crash — missing fields get "<missing>"
    print_results(tmp_path)


def test_print_results_no_experiments(tmp_path, capsys):
    """print_results should print message when no experiments exist."""
    research = tmp_path / ".research"
    research.mkdir()
    (research / "results.tsv").write_text(
        "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
    )
    print_results(tmp_path)
    captured = capsys.readouterr()
    assert "No experiment results" in captured.out


def test_results_json_output(tmp_path, capsys):
    research = tmp_path / ".research"
    research.mkdir()
    (research / "results.tsv").write_text(
        "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
        "2026-03-08T10:00:00\ta1b\tacc\t0.85\t{}\tkeep\tbaseline\n"
    )
    from open_researcher.results_cmd import print_results_json

    print_results_json(tmp_path)
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert len(data) == 1
    assert data[0]["status"] == "keep"


def test_results_chart_no_crash(tmp_path):
    """Chart should not crash even with data."""
    research = tmp_path / ".research"
    research.mkdir()
    (research / "config.yaml").write_text(
        "mode: autonomous\nmetrics:\n  primary:\n    name: acc\n    direction: higher_is_better\n"
    )
    (research / "results.tsv").write_text(
        "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
        "2026-03-08\ta1b\tacc\t0.85\t{}\tkeep\tbaseline\n"
        "2026-03-08\ta2b\tacc\t0.87\t{}\tkeep\texp1\n"
        "2026-03-08\ta3b\tacc\t0.83\t{}\tdiscard\texp2\n"
    )
    from open_researcher.results_cmd import print_results_chart

    # Should not raise
    print_results_chart(tmp_path)


def test_results_chart_empty(tmp_path, capsys):
    research = tmp_path / ".research"
    research.mkdir()
    (research / "results.tsv").write_text(
        "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
    )
    from open_researcher.results_cmd import print_results_chart

    print_results_chart(tmp_path)
    captured = capsys.readouterr()
    assert "No results" in captured.out


def test_derive_final_results_overlays_critic_verdicts(tmp_path):
    research = tmp_path / ".research"
    research.mkdir()
    (research / "results.tsv").write_text(
        "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
        "2026-03-08T10:00:00\ta1b2c3d\tspeedup_ratio\t1.062600\t"
        '"{""_open_researcher_trace"":{""frontier_id"":""frontier-002"",""execution_id"":""exec-002""}}"\tkeep\tidea-002\n'
    )
    (research / "research_graph.json").write_text(
        json.dumps(
            {
                "version": "research-v1",
                "repo_profile": {},
                "hypotheses": [],
                "experiment_specs": [],
                "frontier": [],
                "branch_relations": [],
                "evidence": [
                    {
                        "id": "evi-002",
                        "frontier_id": "frontier-002",
                        "execution_id": "exec-002",
                        "reliability": "needs_repro",
                        "reason_code": "result_observed",
                    }
                ],
                "claim_updates": [
                    {
                        "id": "claim-002",
                        "frontier_id": "frontier-002",
                        "execution_id": "exec-002",
                        "transition": "needs_repro",
                        "reason_code": "supported_but_needs_repro",
                        "reason": "Single run improved benchmark but attribution is still weak",
                    }
                ],
                "counters": {},
            }
        )
    )
    derived = derive_final_results(tmp_path)
    assert len(derived) == 1
    assert derived[0]["raw_status"] == "keep"
    assert derived[0]["final_status"] == "needs_repro"
    assert derived[0]["critic_reason_code"] == "supported_but_needs_repro"


def test_write_final_results_tsv(tmp_path):
    research = tmp_path / ".research"
    research.mkdir()
    (research / "results.tsv").write_text(
        "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
    )
    (research / "research_graph.json").write_text(
        json.dumps(
            {
                "version": "research-v1",
                "repo_profile": {},
                "hypotheses": [],
                "experiment_specs": [],
                "frontier": [],
                "branch_relations": [],
                "evidence": [],
                "claim_updates": [],
                "counters": {},
            }
        )
    )
    write_final_results_tsv(tmp_path)
    final_results = (research / "final_results.tsv").read_text()
    assert final_results.startswith("timestamp\tcommit\tprimary_metric\tmetric_value\traw_status\tfinal_status\t")
