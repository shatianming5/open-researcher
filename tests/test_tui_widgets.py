"""Smoke tests for TUI widgets."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from paperfarm.tui.widgets import (
    FrontierPanel,
    LogPanel,
    MetricChart,
    PhaseStripBar,
    StatsBar,
    WorkerPanel,
)

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

_SAMPLE_SUMMARY = {
    "phase": "manager",
    "round": 3,
    "hypotheses": 5,
    "experiments_total": 10,
    "experiments_done": 4,
    "experiments_running": 2,
    "results_count": 6,
    "best_value": "0.87",
    "workers": [
        {"id": "w0", "status": "running", "gpu": "0", "frontier_id": "F-1"},
        {"id": "w1", "status": "idle", "gpu": "1", "frontier_id": ""},
    ],
    "paused": False,
}

_SAMPLE_FRONTIER = [
    {"id": "F-1", "priority": 10, "status": "running", "description": "Try learning rate 1e-3"},
    {"id": "F-2", "priority": 5, "status": "queued", "description": "Add dropout 0.3"},
    {"id": "F-3", "priority": 20, "status": "queued", "description": "Switch to AdamW"},
]

_SAMPLE_EVENTS = [
    {"ts": "2026-03-18T10:00:00+00:00", "type": "skill_started", "message": "Running scout"},
    {"ts": "2026-03-18T10:01:00+00:00", "type": "skill_completed", "message": "Scout done"},
    {"ts": "2026-03-18T10:02:00+00:00", "type": "experiment_result", "message": "F-1 value=0.87"},
    {"ts": "2026-03-18T10:03:00+00:00", "type": "output", "msg": "Some output line"},
]

_SAMPLE_RESULTS = [
    {"status": "keep", "value": "0.82"},
    {"status": "discard", "value": "0.70"},
    {"status": "keep", "value": "0.87"},
    {"status": "keep", "value": "0.85"},
]


# ---------------------------------------------------------------------------
# TestWidgetInstantiation
# ---------------------------------------------------------------------------


class TestWidgetInstantiation:
    """Verify all widgets can be created without errors."""

    def test_stats_bar(self) -> None:
        w = StatsBar()
        assert w is not None

    def test_phase_strip_bar(self) -> None:
        w = PhaseStripBar()
        assert w is not None

    def test_frontier_panel(self) -> None:
        w = FrontierPanel()
        assert w is not None

    def test_worker_panel(self) -> None:
        w = WorkerPanel()
        assert w is not None

    def test_log_panel(self) -> None:
        w = LogPanel()
        assert w is not None

    def test_metric_chart(self) -> None:
        w = MetricChart()
        assert w is not None


# ---------------------------------------------------------------------------
# TestWidgetUpdate — mount widgets in a minimal App for update tests
# ---------------------------------------------------------------------------


class _TestApp(App):
    """Minimal app that mounts all widgets for testing."""

    def compose(self) -> ComposeResult:
        yield StatsBar(id="stats")
        yield PhaseStripBar(id="phase")
        yield FrontierPanel(id="frontier")
        yield WorkerPanel(id="workers")
        yield LogPanel(id="log")
        yield MetricChart(id="chart")


class TestWidgetUpdate:
    """Call update methods with sample data after mounting."""

    @pytest.fixture()
    def app(self) -> _TestApp:
        return _TestApp()

    async def _run_update(self, app: _TestApp) -> None:
        async with app.run_test() as pilot:
            stats: StatsBar = app.query_one("#stats", StatsBar)
            stats.update_data(_SAMPLE_SUMMARY)
            assert "manager" in str(stats.content)

            phase: PhaseStripBar = app.query_one("#phase", PhaseStripBar)
            phase.update_phase("manager")
            assert "MANAGER" in str(phase.content)

            frontier: FrontierPanel = app.query_one("#frontier", FrontierPanel)
            frontier.update_data(_SAMPLE_FRONTIER)
            table = frontier.query_one("#frontier-table")
            assert table.row_count == 3

            workers: WorkerPanel = app.query_one("#workers", WorkerPanel)
            workers.update_data(_SAMPLE_SUMMARY["workers"])
            wtable = workers.query_one("#worker-table")
            assert wtable.row_count == 2

            log_panel: LogPanel = app.query_one("#log", LogPanel)
            log_panel.update_data(_SAMPLE_EVENTS)

            chart: MetricChart = app.query_one("#chart", MetricChart)
            chart.update_data(_SAMPLE_RESULTS)

    @pytest.mark.asyncio
    async def test_update_all(self, app: _TestApp) -> None:
        await self._run_update(app)

    @pytest.mark.asyncio
    async def test_empty_data(self, app: _TestApp) -> None:
        async with app.run_test() as pilot:
            stats: StatsBar = app.query_one("#stats", StatsBar)
            stats.update_data({})

            phase: PhaseStripBar = app.query_one("#phase", PhaseStripBar)
            phase.update_phase("nonexistent")

            frontier: FrontierPanel = app.query_one("#frontier", FrontierPanel)
            frontier.update_data([])

            workers: WorkerPanel = app.query_one("#workers", WorkerPanel)
            workers.update_data([])

            log_panel: LogPanel = app.query_one("#log", LogPanel)
            log_panel.update_data([])

            chart: MetricChart = app.query_one("#chart", MetricChart)
            chart.update_data([])

    @pytest.mark.asyncio
    async def test_paused_display(self, app: _TestApp) -> None:
        async with app.run_test() as pilot:
            summary = dict(_SAMPLE_SUMMARY, paused=True)
            stats: StatsBar = app.query_one("#stats", StatsBar)
            stats.update_data(summary)
            assert "PAUSED" in str(stats.content)
