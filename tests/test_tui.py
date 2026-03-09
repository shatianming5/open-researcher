"""Tests for Textual TUI components."""

from open_researcher.tui.widgets import AgentPanel, AgentStatusWidget, IdeaPoolPanel, StatsBar


def test_stats_bar_update():
    bar = StatsBar()
    state = {"total": 7, "keep": 3, "discard": 2, "crash": 1, "best_value": 1.47, "primary_metric": "val_loss"}
    bar.update_stats(state)
    assert "7 exp" in bar.stats
    assert "3 kept" in bar.stats
    assert "1.47" in bar.stats


def test_stats_bar_empty():
    bar = StatsBar()
    bar.update_stats({"total": 0})
    assert "waiting" in bar.stats


def test_idea_pool_update():
    panel = IdeaPoolPanel()
    ideas = [
        {
            "id": "idea-001",
            "description": "cosine LR",
            "status": "running",
            "priority": 1,
            "assigned_experiment": 8,
            "result": None,
        },
        {"id": "idea-002", "description": "gradient clip", "status": "pending", "priority": 2, "result": None},
    ]
    summary = {"pending": 1, "running": 1, "done": 0, "skipped": 0, "total": 2}
    panel.update_ideas(ideas, summary)
    assert "cosine LR" in panel.ideas_text
    assert "RUNNING" in panel.ideas_text
    assert "pending" in panel.ideas_text


def test_agent_panel_update():
    panel = AgentPanel()
    activity = {
        "status": "evaluating",
        "idea": "cosine LR",
        "gpu": {"host": "local", "device": 0},
        "branch": "exp/cosine-lr",
    }
    panel.update_from_activity(activity, "Experiment Agent", ["Epoch 4/10 loss=1.43"])
    assert "evaluating" in panel.agent_text
    assert "cosine LR" in panel.agent_text
    assert "Epoch 4" in panel.agent_text


def test_agent_panel_no_activity():
    panel = AgentPanel()
    panel.update_from_activity(None, "Idea Agent")
    assert "idle" in panel.agent_text


def test_worker_status_panel_update():
    from open_researcher.tui.widgets import WorkerStatusPanel

    panel = WorkerStatusPanel()
    workers = [
        {"id": "w-001", "idea": "idea-001", "gpus": [0], "status": "evaluating"},
        {"id": "w-002", "idea": "idea-002", "gpus": [1, 2], "status": "coding"},
    ]
    panel.update_workers(workers, gpu_total=4)
    text = panel.workers_text
    assert "w-001" in text
    assert "GPU:0" in text
    assert "evaluating" in text
    assert "GPU:1,2" in text
    assert "3/4" in text


def test_worker_status_panel_empty():
    from open_researcher.tui.widgets import WorkerStatusPanel

    panel = WorkerStatusPanel()
    panel.update_workers([], gpu_total=0)
    assert "No workers" in panel.workers_text


def test_idea_pool_shows_gpu_info():
    panel = IdeaPoolPanel()
    ideas = [
        {
            "id": "idea-001",
            "description": "cosine LR",
            "status": "running",
            "priority": 1,
            "assigned_experiment": 8,
            "result": None,
            "gpu_hint": 2,
            "claimed_by": "w-001",
        },
    ]
    summary = {"pending": 0, "running": 1, "done": 0, "skipped": 0, "total": 1}
    workers = [{"id": "w-001", "idea": "idea-001", "gpus": [0, 1], "status": "coding"}]
    panel.update_ideas(ideas, summary, workers)
    assert "GPU:0,1" in panel.ideas_text
    assert "DDP" in panel.ideas_text


def test_agent_status_widget_update():
    widget = AgentStatusWidget()
    activity = {
        "status": "analyzing",
        "detail": "reading codebase",
        "updated_at": "2026-03-09T12:00:00",
    }
    widget.update_status(activity)
    assert "ANALYZING" in widget.status_text
    assert "reading codebase" in widget.status_text


def test_agent_status_widget_none():
    widget = AgentStatusWidget()
    widget.update_status(None)
    assert "IDLE" in widget.status_text


def test_agent_status_widget_with_idea():
    widget = AgentStatusWidget()
    activity = {
        "status": "generating",
        "detail": "creating new hypothesis",
        "idea": "cosine-lr-schedule",
        "updated_at": "2026-03-09T14:30:00",
    }
    widget.update_status(activity)
    assert "GENERATING" in widget.status_text
    assert "cosine-lr-schedule" in widget.status_text
    assert "2026-03-09T14:30:00" in widget.status_text
