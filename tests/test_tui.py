"""Tests for Textual TUI components."""

from open_researcher.tui.widgets import (
    ExperimentStatusPanel,
    HotkeyBar,
    IdeaListPanel,
    RecentExperiments,
    StatsBar,
)


def test_stats_bar_colored_output():
    bar = StatsBar()
    state = {
        "total": 7, "keep": 3, "discard": 2, "crash": 1,
        "best_value": 1.47, "primary_metric": "val_loss",
    }
    bar.update_stats(state)
    assert "3 kept" in bar.stats_text
    assert "2 disc" in bar.stats_text
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


def test_idea_list_panel_empty():
    panel = IdeaListPanel()
    panel.update_ideas([])
    assert "No ideas" in panel.ideas_text


def test_hotkey_bar_shows_tabs():
    bar = HotkeyBar()
    rendered = bar.render()
    assert "tabs" in rendered.plain


def test_hotkey_bar_includes_quit():
    bar = HotkeyBar()
    rendered = bar.render()
    assert "q" in str(rendered)


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
