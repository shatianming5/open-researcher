"""Tests for app state machine."""

import json
import tempfile
from pathlib import Path

import pytest


def test_app_state_default():
    """ResearchApp should default to EXPERIMENTING state."""
    from open_researcher.tui.app import ResearchApp

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        research = tmp_path / ".research"
        research.mkdir()
        (research / "idea_pool.json").write_text('{"ideas": []}')
        (research / "activity.json").write_text('{}')

        app = ResearchApp(tmp_path)
        assert app.app_phase == "experimenting"


def test_app_state_scouting():
    """ResearchApp should support scouting state."""
    from open_researcher.tui.app import ResearchApp

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        research = tmp_path / ".research"
        research.mkdir()
        (research / "idea_pool.json").write_text('{"ideas": []}')
        (research / "activity.json").write_text('{}')

        app = ResearchApp(tmp_path, initial_phase="scouting")
        assert app.app_phase == "scouting"


def test_app_bindings_expose_command_center_tabs():
    from open_researcher.tui.app import ResearchApp

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        research = tmp_path / ".research"
        research.mkdir()
        (research / "idea_pool.json").write_text('{"ideas": []}')
        (research / "activity.json").write_text('{}')

        app = ResearchApp(tmp_path)
        bindings = {binding[0]: binding[1] for binding in app.BINDINGS}
        assert bindings["1"] == "switch_tab('tab-command')"
        assert bindings["2"] == "switch_tab('tab-execution')"
        assert bindings["3"] == "switch_tab('tab-logs')"
        assert bindings["4"] == "switch_tab('tab-docs')"


@pytest.mark.asyncio
async def test_docs_sidebar_selection_switches_doc(tmp_path: Path):
    from textual.widgets import Input, OptionList, Static

    from open_researcher.tui.app import ResearchApp
    from open_researcher.tui.view_model import build_docs_workbench
    from open_researcher.tui.widgets import DocViewer, DocsSidebarPanel

    research = tmp_path / ".research"
    research.mkdir()
    (research / "idea_pool.json").write_text('{"ideas": []}', encoding="utf-8")
    (research / "activity.json").write_text("{}", encoding="utf-8")
    (research / "research_graph.json").write_text('{"version":"research-v1"}', encoding="utf-8")
    (research / "evaluation.md").write_text("# Evaluation\n\nMetric details.", encoding="utf-8")

    app = ResearchApp(tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("4")
        doc_viewer = app.query_one("#doc-viewer", DocViewer)
        docs_state = build_docs_workbench(
            research,
            current_file=doc_viewer.current_file,
            doc_files=DocViewer.DOC_FILES,
            dynamic_files=DocViewer.DYNAMIC_FILES,
        )
        app.query_one("#docs-sidebar", DocsSidebarPanel).update_docs(
            docs_state.items,
            current_file=docs_state.current_file,
        )
        await pilot.pause()
        option_list = app.query_one("#docs-options", OptionList)
        option_list.focus()
        assert option_list.option_count >= 5
        initial_option_ids = [option.id for option in option_list.options]
        assert "bootstrap_state.md" in initial_option_ids
        for index, option in enumerate(option_list.options):
            if option.id == "evaluation.md":
                option_list.highlighted = index
                break
        option_list.action_select()
        await pilot.pause()

        viewer = app.query_one("#doc-viewer", DocViewer)
        assert viewer.current_file == "evaluation.md"

        search = app.query_one("#docs-search", Input)
        search.focus()
        await pilot.press("g", "r", "a", "p", "h")
        await pilot.pause()
        prompts = [str(option.prompt) for option in option_list.options]
        option_ids = [option.id for option in option_list.options]
        assert any("Research State" in prompt for prompt in prompts)
        assert "research_graph.md" in option_ids
        assert not any("Evaluation" in prompt for prompt in prompts)

        recent = app.query_one("#docs-recent", Static)
        assert "evaluation.md" in str(recent.render())


@pytest.mark.asyncio
async def test_frontier_selection_updates_detail_drawer(tmp_path: Path):
    from textual.widgets import OptionList

    from open_researcher.tui.app import ResearchApp
    from open_researcher.tui.view_model import build_dashboard_state
    from open_researcher.tui.widgets import FrontierDetailPanel

    research = tmp_path / ".research"
    research.mkdir()
    (research / "idea_pool.json").write_text(
        json.dumps(
            {
                "ideas": [
                    {
                        "id": "idea-001",
                        "frontier_id": "frontier-001",
                        "execution_id": "exec-001",
                        "priority": 1,
                        "status": "pending",
                        "claim_state": "candidate",
                        "hypothesis_summary": "Seed locking reduces variance",
                        "spec_summary": "Run fixed-seed benchmark",
                        "selection_reason_code": "breadth_exploration",
                    },
                    {
                        "id": "idea-002",
                        "frontier_id": "frontier-002",
                        "execution_id": "exec-002",
                        "priority": 2,
                        "status": "pending",
                        "claim_state": "candidate",
                        "hypothesis_summary": "Cache warmup improves latency",
                        "spec_summary": "Prime the cache before benchmark",
                        "selection_reason_code": "exploit_positive_signal",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    (research / "activity.json").write_text("{}", encoding="utf-8")
    (research / "research_graph.json").write_text(
        json.dumps(
            {
                "version": "research-v1",
                "hypotheses": [
                    {"id": "hyp-001", "summary": "Seed locking reduces variance", "rationale": "Order noise"},
                    {"id": "hyp-002", "summary": "Cache warmup improves latency", "rationale": "Cold start cost"},
                ],
                "experiment_specs": [
                    {
                        "id": "spec-001",
                        "hypothesis_id": "hyp-001",
                        "summary": "Run fixed-seed benchmark",
                        "change_plan": "Lock seed and dataloader order.",
                        "evaluation_plan": "Compare variance across 3 runs.",
                    },
                    {
                        "id": "spec-002",
                        "hypothesis_id": "hyp-002",
                        "summary": "Prime the cache before benchmark",
                        "change_plan": "Warm the cache once before timing.",
                        "evaluation_plan": "Compare cold-start and warm-start latency.",
                    },
                ],
                "evidence": [
                    {
                        "id": "evi-002",
                        "frontier_id": "frontier-002",
                        "execution_id": "exec-002",
                        "reason_code": "performance_signal",
                        "reliability": "strong",
                        "description": "latency dropped by 12%",
                        "metric_value": 12.0,
                    }
                ],
                "claim_updates": [],
                "branch_relations": [],
                "frontier": [
                    {
                        "id": "frontier-001",
                        "hypothesis_id": "hyp-001",
                        "experiment_spec_id": "spec-001",
                        "priority": 1,
                        "status": "approved",
                        "claim_state": "candidate",
                        "selection_reason_code": "breadth_exploration",
                    },
                    {
                        "id": "frontier-002",
                        "hypothesis_id": "hyp-002",
                        "experiment_spec_id": "spec-002",
                        "priority": 2,
                        "status": "approved",
                        "claim_state": "candidate",
                        "selection_reason_code": "exploit_positive_signal",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    app = ResearchApp(tmp_path)
    async with app.run_test() as pilot:
        state = {
            "branch": "main",
            "protocol": "research-v1",
            "mode": "autonomous",
            "phase": 5,
            "phase_label": "Research Loop: Experiment Queue Active",
            "primary_metric": "score",
            "direction": "higher_is_better",
            "baseline_value": None,
            "current_value": None,
            "best_value": None,
            "total": 0,
            "keep": 0,
            "discard": 0,
            "crash": 0,
            "graph": {
                "hypotheses": 2,
                "experiment_specs": 2,
                "evidence": 1,
                "claim_updates": 0,
                "frontier_total": 2,
                "frontier_runnable": 2,
                "frontier_status_counts": {"approved": 2},
            },
        }
        dashboard = build_dashboard_state(tmp_path, state=state)
        app._apply_refresh_data(dashboard, state, [])
        await pilot.pause()
        option_list = app.query_one("#frontier-options", OptionList)
        option_list.focus()
        option_list.action_cursor_down()
        await pilot.pause()
        option_list.action_select()
        await pilot.pause()

        detail = app.query_one("#frontier-detail", FrontierDetailPanel)
        assert "Cache warmup improves latency" in detail.body_text
        assert "latency dropped by 12%" in detail.body_text
