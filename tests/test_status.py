import json
import tempfile
from pathlib import Path

from open_researcher.status_cmd import parse_research_state, print_status


def test_parse_state_with_results():
    """Should correctly parse results.tsv and config.yaml."""
    with tempfile.TemporaryDirectory() as tmpdir:
        research = Path(tmpdir, ".research")
        research.mkdir()

        (research / "config.yaml").write_text(
            "mode: autonomous\nmetrics:\n  primary:\n    name: accuracy\n    direction: higher_is_better\n"
        )

        (research / "results.tsv").write_text(
            "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
            "2026-03-08T10:00:00\ta1b2c3d\taccuracy\t0.850000\t{}\tkeep\tbaseline\n"
            "2026-03-08T10:15:00\tb2c3d4e\taccuracy\t0.872000\t{}\tkeep\tincrease LR\n"
            "2026-03-08T10:30:00\tc3d4e5f\taccuracy\t0.840000\t{}\tdiscard\tswitch optimizer\n"
            "2026-03-08T10:45:00\td4e5f6g\taccuracy\t0.000000\t{}\tcrash\tOOM\n"
        )

        # Write filled project understanding
        (research / "project-understanding.md").write_text("# Project\n\nThis is a real project description.")

        # Write filled literature review
        (research / "literature.md").write_text("# Literature Review\n\nFound relevant papers on optimization.")

        # Write filled evaluation
        (research / "evaluation.md").write_text("# Eval\n\nThis uses accuracy as the metric.")

        state = parse_research_state(Path(tmpdir))

        assert state["mode"] == "autonomous"
        assert state["primary_metric"] == "accuracy"
        assert state["direction"] == "higher_is_better"
        assert state["total"] == 4
        assert state["keep"] == 2
        assert state["discard"] == 1
        assert state["crash"] == 1
        assert state["baseline_value"] == 0.85
        assert state["current_value"] == 0.872
        assert state["best_value"] == 0.872
        assert len(state["recent"]) == 4


def test_parse_state_empty():
    """Should handle empty results.tsv (no experiments yet)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        research = Path(tmpdir, ".research")
        research.mkdir()

        (research / "config.yaml").write_text(
            "mode: collaborative\nmetrics:\n  primary:\n    name: ''\n    direction: ''\n"
        )
        (research / "results.tsv").write_text(
            "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
        )
        (research / "project-understanding.md").write_text("<!-- empty -->")
        (research / "evaluation.md").write_text("<!-- empty -->")

        state = parse_research_state(Path(tmpdir))
        assert state["total"] == 0
        assert state["phase"] == 1  # project understanding not filled


def test_detect_phase_2_literature():
    """Phase 2 when project-understanding has content but literature doesn't."""
    with tempfile.TemporaryDirectory() as tmpdir:
        research = Path(tmpdir, ".research")
        research.mkdir()

        (research / "config.yaml").write_text(
            "mode: autonomous\nmetrics:\n  primary:\n    name: ''\n    direction: ''\n"
        )
        (research / "results.tsv").write_text(
            "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
        )
        # Filled project understanding
        (research / "project-understanding.md").write_text("# Project\n\nThis is a real project description.")
        # Empty literature review
        (research / "literature.md").write_text("<!-- empty -->")
        (research / "evaluation.md").write_text("<!-- empty -->")

        state = parse_research_state(Path(tmpdir))
        assert state["phase"] == 2  # literature not filled


def test_detect_phase_3_evaluation():
    """Phase 3 when literature has content but evaluation doesn't."""
    with tempfile.TemporaryDirectory() as tmpdir:
        research = Path(tmpdir, ".research")
        research.mkdir()

        (research / "config.yaml").write_text(
            "mode: autonomous\nmetrics:\n  primary:\n    name: ''\n    direction: ''\n"
        )
        (research / "results.tsv").write_text(
            "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
        )
        (research / "project-understanding.md").write_text("# Project\n\nThis is a real project description.")
        (research / "literature.md").write_text("# Literature Review\n\nFound relevant papers on optimization.")
        (research / "evaluation.md").write_text("<!-- empty -->")

        state = parse_research_state(Path(tmpdir))
        assert state["phase"] == 3  # evaluation not filled


def test_print_status_english_output(capsys):
    """Verify status output uses English, not Chinese."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        research = repo / ".research"
        research.mkdir()
        config = "mode: autonomous\nmetrics:\n  primary:\n    name: accuracy\n    direction: higher_is_better\n"
        (research / "config.yaml").write_text(config)
        header = "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
        (research / "results.tsv").write_text(header)
        (research / "project-understanding.md").write_text("<!-- placeholder -->\n")
        (research / "evaluation.md").write_text("<!-- placeholder -->\n")
        print_status(repo)
        captured = capsys.readouterr()
        assert "Phase 1" in captured.out
        assert "阶段" not in captured.out
        assert "分支" not in captured.out
        assert "模式" not in captured.out
        assert "实验统计" not in captured.out


def test_status_shows_activity(tmp_path):
    """Status should not crash when activity.json exists."""
    research = tmp_path / ".research"
    research.mkdir()
    # Minimal config
    config_text = "mode: autonomous\nmetrics:\n  primary:\n    name: acc\n    direction: higher_is_better\n"
    (research / "config.yaml").write_text(config_text)
    header = "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
    (research / "results.tsv").write_text(header)
    (research / "activity.json").write_text(
        json.dumps(
            {
                "manager_agent": {
                    "status": "analyzing",
                    "detail": "reviewing #3",
                    "updated_at": "2026-03-09T15:00:00Z",
                }
            }
        )
    )
    # Create the docs files as empty
    for name in ["project-understanding.md", "literature.md", "evaluation.md"]:
        (research / name).write_text("# placeholder\n")
    from open_researcher.status_cmd import parse_research_state

    state = parse_research_state(tmp_path)
    assert state is not None
    assert state["total"] == 0


def test_parse_state_includes_research_graph_summary(tmp_path):
    research = tmp_path / ".research"
    research.mkdir()
    config_text = (
        "mode: autonomous\n"
        "research:\n"
        "  protocol: research-v1\n"
        "metrics:\n"
        "  primary:\n"
        "    name: acc\n"
        "    direction: higher_is_better\n"
    )
    (research / "config.yaml").write_text(config_text)
    (research / "results.tsv").write_text(
        "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
    )
    (research / "research_graph.json").write_text(
        json.dumps(
            {
                "version": "research-v1",
                "repo_profile": {},
                "hypotheses": [{"id": "hyp-001"}],
                "experiment_specs": [{"id": "spec-001"}],
                "evidence": [{"id": "evi-001"}],
                "claim_updates": [{"id": "claim-001"}],
                "branch_relations": [],
                "frontier": [{"id": "frontier-001", "status": "approved"}],
                "counters": {},
            }
        )
    )

    state = parse_research_state(tmp_path)

    assert state["protocol"] == "research-v1"
    assert state["graph"]["hypotheses"] == 1
    assert state["graph"]["frontier_runnable"] == 1
    assert "Research Loop" in state["phase_label"]


def test_parse_state_with_corrupt_metric(tmp_path):
    """Should not crash on non-numeric metric values."""
    research = tmp_path / ".research"
    research.mkdir()
    (research / "config.yaml").write_text(
        "mode: autonomous\nmetrics:\n  primary:\n    name: acc\n    direction: higher_is_better\n"
    )
    (research / "results.tsv").write_text(
        "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
        "2026-03-08T10:00:00\ta1b2c3d\tacc\tNaN\t{}\tkeep\tbaseline\n"
        "2026-03-08T11:00:00\tb2c3d4e\tacc\tcorrupt\t{}\tkeep\texp1\n"
    )
    state = parse_research_state(tmp_path)
    assert state["total"] == 2  # Should not crash
    # NaN and "corrupt" should both be filtered out of metric values
    assert state["baseline_value"] is None
    assert state["current_value"] is None
    assert state["best_value"] is None


def test_parse_state_reports_config_error_instead_of_silent_defaults(tmp_path):
    research = tmp_path / ".research"
    research.mkdir()
    (research / "config.yaml").write_text(": :\n  bad: [yaml: broken")
    (research / "results.tsv").write_text(
        "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
    )

    state = parse_research_state(tmp_path)

    assert state["config_error"]
    assert state["protocol_supported"] is False


def test_parse_state_handles_wrong_shaped_graph_json(tmp_path):
    research = tmp_path / ".research"
    research.mkdir()
    (research / "config.yaml").write_text("research:\n  protocol: research-v1\n")
    (research / "results.tsv").write_text(
        "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
    )
    (research / "research_graph.json").write_text(json.dumps({"hypotheses": 1, "frontier": {}}))

    state = parse_research_state(tmp_path)

    assert state["graph"]["error"]


def test_print_status_with_corrupt_metrics(tmp_path):
    """print_status should not crash on non-numeric metric values."""
    research = tmp_path / ".research"
    research.mkdir()
    (research / "config.yaml").write_text(
        "mode: autonomous\nmetrics:\n  primary:\n    name: acc\n    direction: higher_is_better\n"
    )
    (research / "results.tsv").write_text(
        "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
        "2026-03-08T10:00:00\ta1b2c3d\tacc\tNaN\t{}\tkeep\tbaseline\n"
        "2026-03-08T11:00:00\tb2c3d4e\tacc\tcorrupt\t{}\tkeep\texp1\n"
    )
    for name in ["project-understanding.md", "literature.md", "evaluation.md"]:
        (research / name).write_text("# placeholder\nReal content here.\n")
    # Should not crash
    print_status(tmp_path)


def test_sparkline_generation():
    from open_researcher.status_cmd import _sparkline

    result = _sparkline([1.0, 2.0, 3.0, 4.0])
    assert len(result) == 4
    # Should be ascending
    assert result[0] < result[-1] or result == "\u2585\u2585\u2585\u2585"  # handle edge case


def test_sparkline_empty():
    from open_researcher.status_cmd import _sparkline

    assert _sparkline([]) == ""


def test_sparkline_constant():
    from open_researcher.status_cmd import _sparkline

    result = _sparkline([5.0, 5.0, 5.0])
    assert len(result) == 3
    # All same value -> all same char
    assert result[0] == result[1] == result[2]


def test_parse_state_includes_runtime_profile_summary(tmp_path, monkeypatch):
    research = tmp_path / ".research"
    research.mkdir()
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    (research / "config.yaml").write_text(
        "mode: autonomous\n"
        "research:\n"
        "  protocol: research-v1\n"
        "experiment:\n"
        "  max_parallel_workers: 4\n"
        "runtime:\n"
        "  gpu_allocation: false\n"
        "  failure_memory: false\n"
        "  worktree_isolation: true\n"
    )
    (research / "results.tsv").write_text(
        "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
    )
    for name in ["project-understanding.md", "literature.md", "evaluation.md"]:
        (research / name).write_text("# placeholder\nReal content.\n")

    state = parse_research_state(tmp_path)

    runtime = state["runtime"]
    assert runtime["mode"] == "parallel"
    assert runtime["requested_workers"] == 4
    assert runtime["effective_workers"] == 4
    assert runtime["profile_name"] == "custom"
    assert runtime["plugins"]["gpu_allocation"] is False
    assert runtime["plugins"]["failure_memory"] is False
    assert runtime["plugins"]["worktree_isolation"] is True
    assert runtime["frontier_projection_target"] == 4


def test_parse_state_handles_non_integer_worker_config_without_crash(tmp_path):
    research = tmp_path / ".research"
    research.mkdir()
    (research / "config.yaml").write_text(
        "mode: autonomous\n"
        "research:\n"
        "  protocol: research-v1\n"
        "experiment:\n"
        '  max_parallel_workers: "auto"\n'
    )
    (research / "results.tsv").write_text(
        "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
    )
    for name in ["project-understanding.md", "literature.md", "evaluation.md"]:
        (research / name).write_text("# placeholder\nReal content.\n")

    state = parse_research_state(tmp_path)

    runtime = state["runtime"]
    assert runtime["requested_workers"] == "auto"
    assert runtime["effective_workers"] == 1
    assert "Invalid experiment.max_parallel_workers" in runtime["clamp_reason"]


def test_parse_state_includes_observability_summary(tmp_path):
    research = tmp_path / ".research"
    research.mkdir()
    (research / "config.yaml").write_text("research:\n  protocol: research-v1\n")
    (research / "results.tsv").write_text(
        "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
    )
    (research / "events.jsonl").write_text(
        '{"seq":1,"event":"session_started"}\n'
        "not-json\n"
        '{"seq":3,"event":"session_finished"}\n'
    )
    (research / "control.json").write_text("{}")
    (research / "activity.json").write_text("{}")
    runtime_dir = research / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "idea-001__exec-001.json").write_text("{}")
    (runtime_dir / "idea-002__exec-002.json").write_text("{}")

    state = parse_research_state(tmp_path)

    observability = state["observability"]
    assert observability["events_exists"] is True
    assert observability["event_count"] == 2
    assert observability["last_seq"] == 3
    assert observability["parse_errors"] == 1
    assert observability["runtime_registrations"] == 2
    snapshot_exists = {item["name"]: item["exists"] for item in observability["snapshots"]}
    assert snapshot_exists == {"control": True, "activity": True, "gpu_status": False}


def test_parse_state_observability_handles_invalid_utf8_events_file(tmp_path):
    research = tmp_path / ".research"
    research.mkdir()
    (research / "config.yaml").write_text("research:\n  protocol: research-v1\n")
    (research / "results.tsv").write_text(
        "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
    )
    (research / "events.jsonl").write_bytes(b"\xff\xfe\xfd")

    state = parse_research_state(tmp_path)

    observability = state["observability"]
    assert observability["events_exists"] is True
    assert observability["event_count"] == 0
    assert observability["parse_errors"] >= 1


def test_observability_loader_streams_without_read_text(tmp_path, monkeypatch):
    from open_researcher.status_cmd import _load_observability_state

    research = tmp_path / ".research"
    research.mkdir()
    (research / "events.jsonl").write_text(
        '{"seq":1,"event":"session_started"}\n'
        '{"seq":2,"event":"step"}\n'
    )

    def _fail_read_text(*_args, **_kwargs):
        raise AssertionError("read_text should not be used by observability loader")

    monkeypatch.setattr(Path, "read_text", _fail_read_text)

    observability = _load_observability_state(research)
    assert observability["event_count"] == 2
    assert observability["last_seq"] == 2
    assert observability["parse_errors"] == 0


def test_print_status_shows_runtime_profile_and_observability(tmp_path, capsys):
    research = tmp_path / ".research"
    research.mkdir()
    (research / "config.yaml").write_text(
        "mode: autonomous\n"
        "research:\n"
        "  protocol: research-v1\n"
        "experiment:\n"
        "  max_parallel_workers: 2\n"
    )
    (research / "results.tsv").write_text(
        "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
    )
    (research / "events.jsonl").write_text('{"seq":1,"event":"session_started"}\n')
    (research / "control.json").write_text("{}")
    (research / "activity.json").write_text("{}")
    for name in ["project-understanding.md", "literature.md", "evaluation.md"]:
        (research / name).write_text("# placeholder\nReal content.\n")

    print_status(tmp_path)
    captured = capsys.readouterr()

    assert "Runtime Profile" in captured.out
    assert "Observability" in captured.out
    assert "events.jsonl" in captured.out
    assert "events.jsonl is canonical" in captured.out
