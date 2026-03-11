"""Tests for Textual TUI components."""

from open_researcher.tui.widgets import (
    BootstrapStatusPanel,
    DocsSidebarPanel,
    ExperimentStatusPanel,
    FrontierDetailPanel,
    FrontierFocusPanel,
    HotkeyBar,
    IdeaListPanel,
    LineageTimelinePanel,
    RecentExperiments,
    SessionChromeBar,
    StatsBar,
    TraceBanner,
    render_ideas_markdown,
)
from open_researcher.tui.view_model import (
    BootstrapSummary,
    ClaimItem,
    DocNavItem,
    EvidenceItem,
    FrontierCard,
    FrontierDetail,
    LineageItem,
    SessionChrome,
    TimelineItem,
)


def test_stats_bar_colored_output():
    bar = StatsBar()
    state = {
        "total": 7, "keep": 3, "discard": 2, "crash": 1,
        "best_value": 1.47, "primary_metric": "val_loss",
    }
    bar.update_stats(state)
    assert "3K" in bar.stats_text
    assert "2D" in bar.stats_text
    assert "1.47" in bar.stats_text


def test_stats_bar_empty():
    bar = StatsBar()
    bar.update_stats({"total": 0})
    assert "waiting" in bar.stats_text


def test_experiment_status_panel_running():
    panel = ExperimentStatusPanel()
    activity = {
        "status": "running", "detail": "implementing code changes",
        "idea": "idea-003", "updated_at": "2026-03-09T12:00:00",
    }
    panel.update_status(activity, completed=3, total=10)
    assert "RUNNING" in panel.status_text
    assert "idea-003" in panel.status_text
    assert "3" in panel.status_text and "10" in panel.status_text


def test_experiment_status_panel_idle():
    panel = ExperimentStatusPanel()
    panel.update_status(None, completed=0, total=0)
    assert "IDLE" in panel.status_text


def test_experiment_status_panel_baseline():
    panel = ExperimentStatusPanel()
    activity = {"status": "establishing_baseline", "detail": "running baseline"}
    panel.update_status(activity, completed=0, total=5)
    assert "BASELINE" in panel.status_text or "baseline" in panel.status_text


def test_idea_list_panel_renders():
    panel = IdeaListPanel()
    ideas = [
        {"id": "idea-001", "description": "Add dropout", "status": "done",
         "priority": 1, "result": {"metric_value": 1.23, "verdict": "kept"}},
        {"id": "idea-002", "description": "Batch norm", "status": "running",
         "priority": 2, "result": None},
        {"id": "idea-003", "description": "LR warmup", "status": "pending",
         "priority": 3, "result": None},
    ]
    panel.update_ideas(ideas)
    text = panel.ideas_text
    lines = text.strip().split("\n")
    assert len(lines) == 3
    assert "\u25b6" in text
    assert "\u2713" in text
    assert "\u00b7" in text
    assert "idea-001" in text


def test_idea_list_panel_empty():
    panel = IdeaListPanel()
    panel.update_ideas([])
    assert "No projected backlog items" in panel.ideas_text


def test_hotkey_bar_shows_tabs():
    bar = HotkeyBar()
    rendered = bar.render()
    assert "tabs" in str(rendered)


def test_hotkey_bar_includes_quit():
    bar = HotkeyBar()
    rendered = bar.render()
    assert "q" in str(rendered)


def test_session_chrome_bar_renders_protocol_and_metric():
    widget = SessionChromeBar()
    widget.update_chrome(
        SessionChrome(
            branch="main",
            protocol="research-v1",
            mode="autonomous",
            phase="experimenting",
            phase_label="Research Loop: Experiment Queue Active",
            paused=False,
            skip_current=False,
            primary_metric="score",
            direction="higher_is_better",
            baseline_value=0.81,
            current_value=0.84,
            best_value=0.85,
            total=4,
            keep=2,
            discard=1,
            crash=1,
            frontier_runnable=3,
        )
    )
    assert "research-v1" in widget.chrome_text
    assert "main" in widget.chrome_text
    assert "0.8500" in widget.chrome_text


def test_bootstrap_status_panel_renders_prepare_summary():
    panel = BootstrapStatusPanel()
    panel.update_summary(
        BootstrapSummary(
            status="running",
            working_dir=".",
            python_executable="/tmp/demo/.venv/bin/python",
            install_status="completed",
            data_status="running",
            smoke_status="pending",
            log_path=".research/prepare.log",
            unresolved=["Smoke command inferred from evaluation.md"],
            missing_paths=["data/ready.txt"],
        )
    )
    assert "Repository Prepare" in panel.summary_text
    assert "prepare.log" in panel.summary_text
    assert "data/ready.txt" in panel.summary_text


def test_trace_banner_renders_latest_trace():
    widget = TraceBanner()
    widget.update_trace("frontier-001 / exec-001 / breadth_exploration")
    assert "frontier-001" in widget.banner_text
    assert "exec-001" in widget.banner_text


def test_frontier_focus_panel_renders_research_cards():
    panel = FrontierFocusPanel()
    panel.update_frontiers(
        [
            FrontierCard(
                frontier_id="frontier-001",
                execution_id="exec-001",
                idea_id="idea-001",
                priority=1,
                status="approved",
                claim_state="candidate",
                repro_required=True,
                hypothesis_summary="Try seed-stable evaluation",
                spec_summary="Lock dataloader order and compare variance",
                description="Re-run evaluation with fixed seed",
                attribution_focus="Evaluation stability",
                expected_signal="Variance decreases",
                risk_level="low",
                reason_code="approved_for_execution",
                metric_value="0.84",
            )
        ]
    )
    assert "frontier-001" in panel.items_text
    assert "REPRO" in panel.items_text
    assert "approved_for_execution" in panel.items_text


def test_frontier_detail_panel_renders_selected_frontier_payload():
    panel = FrontierDetailPanel()
    panel.update_detail(
        FrontierDetail(
            frontier=FrontierCard(
                frontier_id="frontier-001",
                execution_id="exec-001",
                idea_id="idea-001",
                priority=1,
                status="approved",
                claim_state="candidate",
                repro_required=True,
                hypothesis_summary="Seed locking reduces variance",
                spec_summary="Run fixed-seed benchmark",
                description="Re-run with fixed seed",
                attribution_focus="Evaluation stability",
                expected_signal="variance down",
                risk_level="low",
                reason_code="approved_for_execution",
            ),
            hypothesis_id="hyp-001",
            hypothesis_rationale="Random order may be masking signal.",
            expected_evidence=["variance down", "same mean score"],
            experiment_spec_id="spec-001",
            change_plan="Lock seed and dataloader order.",
            evaluation_plan="Run benchmark three times and compare variance.",
            primary_metric="score",
            direction="higher_is_better",
            baseline_value=0.78,
            current_value=0.80,
            global_best_value=0.84,
            latest_metric_value=0.82,
            best_metric_value=0.82,
            metric_samples=1,
            evidence=[
                EvidenceItem(
                    evidence_id="evi-001",
                    frontier_id="frontier-001",
                    execution_id="exec-001",
                    reliability="strong",
                    reason_code="result_observed",
                    description="variance dropped by 40%",
                    metric_value="0.82",
                )
            ],
            claims=[
                ClaimItem(
                    claim_update_id="claim-001",
                    frontier_id="frontier-001",
                    execution_id="exec-001",
                    transition="promote",
                    confidence="high",
                    reason_code="supported_by_strong_evidence",
                )
            ],
        )
    )
    assert "Seed locking reduces variance" in panel.body_text
    assert "variance dropped by 40%" in panel.body_text
    assert "claim-001" in panel.body_text
    assert "vs baseline" in panel.body_text
    assert "best observed" in panel.body_text


def test_lineage_timeline_panel_renders_branch_and_timeline():
    panel = LineageTimelinePanel()
    panel.update_items(
        [
            LineageItem(
                relation="refines",
                parent_id="hyp-001",
                child_id="hyp-002",
                parent_summary="Baseline stabilizes poorly",
                child_summary="Seed locking reduces variance",
            )
        ],
        [
            TimelineItem(
                ts="2026-03-11T10:00:00Z",
                event="experiment_started",
                phase="experimenting",
                frontier_id="frontier-001",
                execution_id="exec-001",
                reason_code="breadth_exploration",
                detail="run #1 started",
            )
        ],
    )
    assert "hyp-001" in panel.body_text
    assert "experiment_started" in panel.body_text
    assert "frontier-001" in panel.body_text


def test_docs_sidebar_panel_renders_active_doc_preview():
    panel = DocsSidebarPanel()
    panel.update_docs(
        [
            DocNavItem(
                filename="research_graph.md",
                title="Research Graph",
                available=True,
                dynamic=True,
                preview="Generated from canonical JSON state",
            ),
            DocNavItem(
                filename="evaluation.md",
                title="Evaluation",
                available=False,
                dynamic=False,
                preview="Missing",
            ),
        ],
        current_file="research_graph.md",
    )
    assert "Research Graph" in panel.body_text
    assert "LIVE" in panel.body_text
    assert "Missing" in panel.body_text


def test_recent_experiments_renders():
    widget = RecentExperiments()
    rows = [
        {"status": "keep", "metric_value": "0.85", "description": "baseline"},
        {"status": "discard", "metric_value": "0.80", "description": "exp1"},
    ]
    widget.update_results(rows)
    assert "0.85" in widget.results_text
    assert "0.80" in widget.results_text


def test_recent_experiments_empty():
    widget = RecentExperiments()
    widget.update_results([])
    assert "No experiments" in widget.results_text


def test_render_ideas_markdown_empty():
    result = render_ideas_markdown([])
    assert "No projected backlog items yet" in result
    assert "Projected Backlog" in result


def test_render_ideas_markdown_with_data():
    ideas = [
        {"id": "idea-001", "description": "Add dropout", "category": "regularization",
         "priority": 1, "status": "done",
         "result": {"metric_value": 0.85, "verdict": "kept"}},
        {"id": "idea-002", "description": "Batch norm", "category": "architecture",
         "priority": 2, "status": "running", "result": None},
        {"id": "idea-003", "description": "LR warmup", "category": "training",
         "priority": 3, "status": "pending", "result": None},
    ]
    result = render_ideas_markdown(ideas)
    assert "idea-001" in result
    assert "Add dropout" in result
    assert "0.85" in result
    assert "kept" in result
    assert "running..." in result
    assert "1 pending" in result
    assert "1 running" in result
    assert "1 done" in result
    assert "3 total projected backlog items" in result


def test_render_ideas_markdown_escapes_pipe():
    ideas = [
        {"id": "idea-001", "description": "Use A|B config", "category": "test|cat",
         "priority": 1, "status": "pending", "result": None},
    ]
    result = render_ideas_markdown(ideas)
    assert "A\\|B" in result
    assert "test\\|cat" in result


def test_backlog_rendering_sorts_by_priority_not_id():
    panel = IdeaListPanel()
    ideas = [
        {"id": "idea-010", "description": "Low priority", "status": "pending", "priority": 10, "result": None},
        {"id": "idea-002", "description": "High priority", "status": "pending", "priority": 1, "result": None},
    ]
    panel.update_ideas(ideas)
    lines = panel.ideas_text.splitlines()
    assert "idea-002" in lines[0]

    markdown = render_ideas_markdown(ideas)
    assert markdown.index("idea-002") < markdown.index("idea-010")
