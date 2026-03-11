"""Tests for TUI dashboard view-model aggregation."""

from pathlib import Path

from open_researcher.tui.view_model import build_dashboard_state, build_docs_workbench


def test_build_dashboard_state_aggregates_graph_and_roles(tmp_path: Path):
    research = tmp_path / ".research"
    research.mkdir()

    (research / "research_graph.json").write_text(
        """
        {
          "version": "research-v1",
          "hypotheses": [{"id": "hyp-001", "summary": "Seed locking reduces variance"}],
          "experiment_specs": [{"id": "spec-001", "hypothesis_id": "hyp-001", "summary": "Run fixed-seed benchmark", "expected_signal": "variance down", "risk_level": "low"}],
          "evidence": [{"id": "evi-001", "frontier_id": "frontier-001", "execution_id": "exec-001", "reason_code": "result_observed", "reliability": "strong", "description": "variance drop", "metric_value": 0.82}],
          "claim_updates": [{"id": "claim-001", "frontier_id": "frontier-001", "execution_id": "exec-001", "transition": "promote", "confidence": "high", "reason_code": "supported_by_strong_evidence"}],
          "branch_relations": [{"id": "rel-001", "parent_hypothesis_id": "hyp-000", "child_hypothesis_id": "hyp-001", "relation": "refines"}],
          "frontier": [{"id": "frontier-001", "hypothesis_id": "hyp-001", "experiment_spec_id": "spec-001", "priority": 1, "status": "approved", "claim_state": "candidate", "selection_reason_code": "breadth_exploration"}]
        }
        """,
        encoding="utf-8",
    )
    (research / "research_memory.json").write_text(
        """
        {
          "repo_type_priors": [{"key": "general_code"}],
          "ideation_memory": [{"id": "mem-001"}],
          "experiment_memory": [{"id": "mem-002"}, {"id": "mem-003"}]
        }
        """,
        encoding="utf-8",
    )

    state = {
        "branch": "main",
        "protocol": "research-v1",
        "mode": "autonomous",
        "phase": 5,
        "phase_label": "Research Loop: Experiment Queue Active",
        "primary_metric": "score",
        "direction": "higher_is_better",
        "baseline_value": 0.80,
        "current_value": 0.82,
        "best_value": 0.83,
        "total": 2,
        "keep": 1,
        "discard": 1,
        "crash": 0,
        "graph": {
            "hypotheses": 1,
            "experiment_specs": 1,
            "evidence": 1,
            "claim_updates": 1,
            "frontier_total": 1,
            "frontier_runnable": 1,
            "frontier_status_counts": {"approved": 1},
        },
        "bootstrap": {
            "status": "completed",
            "working_dir": ".",
            "python_executable": "/tmp/demo/.venv/bin/python",
            "steps": {
                "install": {"status": "completed"},
                "data": {"status": "completed"},
                "smoke": {"status": "completed"},
            },
            "errors": [],
            "unresolved": [],
            "expected_path_status": [{"path": "data/ready.txt", "exists": True}],
            "log_path": ".research/prepare.log",
        },
    }
    ideas = [
        {
            "id": "idea-001",
            "frontier_id": "frontier-001",
            "execution_id": "exec-001",
            "priority": 1,
            "status": "pending",
            "claim_state": "candidate",
            "repro_required": True,
            "hypothesis_summary": "Seed locking reduces variance",
            "spec_summary": "Run fixed-seed benchmark",
            "expected_signal": "variance down",
            "risk_level": "low",
            "selection_reason_code": "breadth_exploration",
        }
    ]
    activities = {
        "manager_agent": {"status": "running", "detail": "ranking frontier", "frontier_id": "frontier-001"},
        "critic_agent": {"status": "idle", "detail": ""},
        "experiment_agent": {"status": "idle", "detail": ""},
    }
    rows = [
        {"status": "keep", "metric_value": "0.80", "description": "baseline"},
        {"status": "discard", "metric_value": "0.82", "description": "seed lock"},
    ]

    dashboard = build_dashboard_state(
        tmp_path,
        state=state,
        ideas=ideas,
        activities=activities,
        rows=rows,
        control={"paused": True, "skip_current": False},
        trace_banner="frontier-001 / exec-001 / breadth_exploration",
    )

    assert dashboard.session.paused is True
    assert dashboard.bootstrap.status == "completed"
    assert dashboard.bootstrap.smoke_status == "completed"
    assert dashboard.graph.ideation_memory == 1
    assert dashboard.graph.experiment_memory == 2
    assert dashboard.frontiers[0].frontier_id == "frontier-001"
    assert dashboard.frontier_details["frontier-001"].experiment_spec_id == "spec-001"
    assert dashboard.frontier_details["frontier-001"].latest_metric_value == 0.82
    assert dashboard.frontier_details["frontier-001"].best_metric_value == 0.82
    assert dashboard.roles[0].status == "running"
    assert dashboard.evidence[0].evidence_id == "evi-001"
    assert dashboard.claims[0].claim_update_id == "claim-001"
    assert dashboard.lineage[0].relation == "refines"
    assert dashboard.trace_banner.endswith("breadth_exploration")


def test_build_docs_workbench_collects_availability_and_preview(tmp_path: Path):
    research = tmp_path / ".research"
    research.mkdir()
    (research / "research_graph.json").write_text('{"version":"research-v1"}', encoding="utf-8")
    (research / "bootstrap_state.json").write_text('{"status":"completed"}', encoding="utf-8")
    (research / "evaluation.md").write_text("# Evaluation\n\nCheck reproducibility first.", encoding="utf-8")

    docs = build_docs_workbench(
        research,
        current_file="evaluation.md",
        doc_files=["research_graph.md", "bootstrap_state.md", "evaluation.md", "literature.md"],
        dynamic_files={"research_graph.md", "bootstrap_state.md"},
    )

    assert docs.current_file == "evaluation.md"
    assert docs.items[0].available is True
    assert docs.items[0].dynamic is True
    assert docs.items[0].group == "Research State"
    assert docs.items[1].available is True
    assert docs.items[1].dynamic is True
    assert docs.items[1].group == "Research State"
    assert docs.items[2].preview == "Check reproducibility first."
    assert docs.items[2].group == "Research Notes"
    assert docs.items[3].available is False
