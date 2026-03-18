"""End-to-end TUI tests with simulated runner lifecycle.

These tests verify the REAL display pipeline:
  FakeRunner(thread) → state files → poll timer → widget rendering

Each test has a hard timeout — if the TUI hangs, the test FAILS with timeout.
"""

from __future__ import annotations

import asyncio
import time
import threading
from pathlib import Path
from typing import Any

import pytest
from textual.widgets import DataTable, RichLog

from paperfarm.state import ResearchState
from paperfarm.tui.app import ResearchApp
from paperfarm.tui.widgets import (
    FrontierPanel, LogPanel, MetricChart, PhaseStripBar, StatsBar, WorkerPanel,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(tmp_path: Path) -> ResearchState:
    d = tmp_path / ".research"
    d.mkdir(parents=True, exist_ok=True)
    return ResearchState(d)


def _get_rendered_text(app: ResearchApp, widget_id: str) -> str:
    """Get the actual rendered content of a Static-based widget as a string."""
    widget = app.query_one(f"#{widget_id}")
    # For Static widgets, .content gives the Rich markup string
    if hasattr(widget, "content"):
        return str(widget.content)
    return ""


async def _wait_for_condition(
    condition, *, timeout: float = 5.0, interval: float = 0.2, msg: str = ""
):
    """Poll until condition() is truthy or timeout. Raises on timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        await asyncio.sleep(interval)
    raise AssertionError(f"Timed out waiting for: {msg or 'condition'}")


# ---------------------------------------------------------------------------
# FakeRunner: simulates a multi-phase research session
# ---------------------------------------------------------------------------


class FakeRunner:
    """Simulates state transitions like a real SkillRunner.run_serial().

    Each step writes to state files with small delays, exactly like
    the real runner thread would.
    """

    def __init__(self, state: ResearchState, *, fail_at: str = "") -> None:
        self.state = state
        self.fail_at = fail_at  # e.g. "scout", "manager", "experiment"
        self.finished = threading.Event()
        self.exit_code = 0

    def __call__(self) -> int:
        try:
            return self._run()
        finally:
            self.finished.set()

    def _run(self) -> int:
        s = self.state

        # -- session start --
        s.append_log({"event": "session_started"})

        # -- bootstrap (scout) --
        s.update_phase("scout")
        s.append_log({"event": "skill_started", "step": "scout", "skill": "scout.md"})
        time.sleep(0.1)
        s.append_log({"event": "agent_output", "phase": "scout", "line": "Analyzing repository..."})
        time.sleep(0.1)

        if self.fail_at == "scout":
            s.append_log({"event": "agent_output", "phase": "scout", "line": "Error: auth failed"})
            s.append_log({"event": "skill_completed", "step": "scout", "skill": "scout.md", "exit_code": 1})
            s.update_phase("failed")
            s.append_log({"event": "session_ended", "status": "failed", "stage": "bootstrap", "exit_code": 1})
            self.exit_code = 1
            return 1

        # Scout produces graph + config
        s.save_graph({
            "hypotheses": [
                {"id": "H-1", "text": "Optimize loop unrolling"},
                {"id": "H-2", "text": "Reduce memory allocations"},
            ],
            "frontier": [],
            "counters": {"hypothesis": 2, "frontier": 0},
        })
        s.append_log({"event": "skill_completed", "step": "scout", "skill": "scout.md", "exit_code": 0})

        # -- round 1 --
        s.update_phase("round", 1)
        s.append_log({"event": "round_started", "round": 1})

        # Manager
        s.update_phase("manager")
        s.append_log({"event": "skill_started", "step": "manager", "skill": "manager.md"})
        time.sleep(0.1)

        if self.fail_at == "manager":
            s.append_log({"event": "skill_completed", "step": "manager", "skill": "manager.md", "exit_code": 1})
            s.update_phase("failed")
            s.append_log({"event": "session_ended", "status": "failed", "stage": "round_1", "exit_code": 1})
            self.exit_code = 1
            return 1

        # Manager produces frontier items
        s.save_graph({
            "hypotheses": [
                {"id": "H-1", "text": "Optimize loop unrolling"},
                {"id": "H-2", "text": "Reduce memory allocations"},
            ],
            "frontier": [
                {"id": "F-1", "priority": 0.9, "status": "pending", "description": "Loop unroll benchmark"},
                {"id": "F-2", "priority": 0.6, "status": "pending", "description": "Memory pool allocator"},
            ],
            "counters": {"hypothesis": 2, "frontier": 2},
        })
        s.append_log({"event": "skill_completed", "step": "manager", "skill": "manager.md", "exit_code": 0})

        # Critic
        s.update_phase("critic")
        s.append_log({"event": "skill_started", "step": "critic", "skill": "critic.md"})
        time.sleep(0.1)
        s.append_log({"event": "skill_completed", "step": "critic", "skill": "critic.md", "exit_code": 0})

        # Experiment
        s.update_phase("experiment")
        s.append_log({"event": "skill_started", "step": "experiment", "skill": "experiment.md"})
        time.sleep(0.1)

        if self.fail_at == "experiment":
            s.append_log({"event": "skill_completed", "step": "experiment", "skill": "experiment.md", "exit_code": 1})
            s.update_phase("failed")
            s.append_log({"event": "session_ended", "status": "failed", "stage": "round_1", "exit_code": 1})
            self.exit_code = 1
            return 1

        # Experiment updates workers + results
        s.update_worker("w0", status="running", gpu="cuda:0", frontier_id="F-1")
        time.sleep(0.1)
        s.append_log({"event": "worker_started", "worker": "w0", "frontier_id": "F-1"})
        s.append_result({
            "worker": "w0", "frontier_id": "F-1", "status": "keep",
            "metric": "latency_ms", "value": "12.3", "description": "Loop unroll v1",
        })
        s.append_log({"event": "experiment_result", "message": "F-1: 12.3ms (keep)"})
        s.update_worker("w0", status="idle", frontier_id="")
        s.append_log({"event": "worker_finished", "worker": "w0", "frontier_id": "F-1"})

        # Mark frontier item as done
        graph = s.load_graph()
        for f in graph.get("frontier", []):
            if f["id"] == "F-1":
                f["status"] = "archived"
        s.save_graph(graph)

        s.append_log({"event": "skill_completed", "step": "experiment", "skill": "experiment.md", "exit_code": 0})

        # Critic again
        s.update_phase("critic")
        s.append_log({"event": "skill_started", "step": "critic", "skill": "critic.md"})
        time.sleep(0.1)
        s.append_log({"event": "skill_completed", "step": "critic", "skill": "critic.md", "exit_code": 0})

        s.append_log({"event": "round_completed", "round": 1})

        # -- session complete --
        s.update_phase("idle")
        s.append_log({"event": "session_ended", "status": "completed"})
        return 0


# ---------------------------------------------------------------------------
# Test: Full lifecycle — happy path
# ---------------------------------------------------------------------------


class TestLifecycleHappyPath:
    """Full runner lifecycle: scout → manager → critic → experiment → done."""

    @pytest.mark.asyncio
    @pytest.mark.timeout(15)
    async def test_tui_progresses_through_all_phases(self, tmp_path: Path) -> None:
        """TUI should reflect each phase as the runner progresses."""
        state = _make_state(tmp_path)
        runner = FakeRunner(state)
        app = ResearchApp(repo_path=str(tmp_path), state=state, runner=runner)

        async with app.run_test() as pilot:
            # Wait for runner to finish (it takes ~0.7s total)
            await _wait_for_condition(
                lambda: runner.finished.is_set(),
                timeout=5.0, msg="runner to finish",
            )

            # Let a few polls happen to pick up final state
            await pilot.pause()
            await asyncio.sleep(1.5)
            await pilot.pause()

            # -- Verify StatsBar shows final state --
            stats_text = _get_rendered_text(app, "stats")
            # Phase should be idle (completed) with round 1
            assert "idle" in stats_text.lower() or "1" in stats_text, \
                f"StatsBar should show idle/round 1, got: {stats_text}"

            # -- Verify PhaseStripBar rendered --
            phase_text = _get_rendered_text(app, "phase")
            assert phase_text, "PhaseStripBar should not be empty"

            # -- Verify FrontierPanel has rows --
            table: DataTable = app.query_one("#frontier-table", DataTable)
            assert table.row_count == 2, f"Expected 2 frontier items, got {table.row_count}"

            # -- Verify WorkerPanel rendered workers at some point --
            # (workers may be idle now, but table should exist and be queryable)
            worker_table: DataTable = app.query_one("#worker-table", DataTable)
            assert worker_table is not None

            # -- Verify LogPanel has events --
            log_panel: LogPanel = app.query_one("#log", LogPanel)
            assert log_panel._seen_count > 10, \
                f"Expected >10 log events, got {log_panel._seen_count}"

            # -- Verify MetricChart shows results --
            chart_text = _get_rendered_text(app, "chart")
            assert "No kept results" not in chart_text, \
                f"MetricChart should show results, got: {chart_text}"

    @pytest.mark.asyncio
    @pytest.mark.timeout(15)
    async def test_session_ended_in_log(self, tmp_path: Path) -> None:
        """Log should contain session_ended with completed status."""
        state = _make_state(tmp_path)
        runner = FakeRunner(state)
        app = ResearchApp(repo_path=str(tmp_path), state=state, runner=runner)

        async with app.run_test() as pilot:
            await _wait_for_condition(
                lambda: runner.finished.is_set(), timeout=5.0, msg="runner done",
            )
            await asyncio.sleep(1.5)
            await pilot.pause()

            events = state.tail_log(50)
            types = [e.get("event") for e in events]
            assert "session_started" in types
            assert "session_ended" in types
            assert events[-1].get("status") == "completed"


# ---------------------------------------------------------------------------
# Test: Failed at different stages
# ---------------------------------------------------------------------------


class TestLifecycleFailures:

    @pytest.mark.asyncio
    @pytest.mark.timeout(10)
    async def test_fail_at_scout_shows_failed(self, tmp_path: Path) -> None:
        state = _make_state(tmp_path)
        runner = FakeRunner(state, fail_at="scout")
        app = ResearchApp(repo_path=str(tmp_path), state=state, runner=runner)

        async with app.run_test() as pilot:
            await _wait_for_condition(
                lambda: runner.finished.is_set(), timeout=5.0, msg="runner fail",
            )
            await asyncio.sleep(1.5)
            await pilot.pause()

            stats_text = _get_rendered_text(app, "stats")
            assert "FAILED" in stats_text, f"StatsBar should show FAILED, got: {stats_text}"

            phase_text = _get_rendered_text(app, "phase")
            assert "FAILED" in phase_text, f"PhaseBar should show FAILED, got: {phase_text}"

    @pytest.mark.asyncio
    @pytest.mark.timeout(10)
    async def test_fail_at_manager_shows_failed(self, tmp_path: Path) -> None:
        state = _make_state(tmp_path)
        runner = FakeRunner(state, fail_at="manager")
        app = ResearchApp(repo_path=str(tmp_path), state=state, runner=runner)

        async with app.run_test() as pilot:
            await _wait_for_condition(
                lambda: runner.finished.is_set(), timeout=5.0, msg="runner fail",
            )
            await asyncio.sleep(1.5)
            await pilot.pause()

            stats_text = _get_rendered_text(app, "stats")
            assert "FAILED" in stats_text

            # Should have hypotheses from scout but no frontier from manager
            events = state.tail_log(50)
            session_end = [e for e in events if e.get("event") == "session_ended"]
            assert len(session_end) == 1
            assert session_end[0].get("stage") == "round_1"

    @pytest.mark.asyncio
    @pytest.mark.timeout(10)
    async def test_fail_at_experiment_shows_failed(self, tmp_path: Path) -> None:
        state = _make_state(tmp_path)
        runner = FakeRunner(state, fail_at="experiment")
        app = ResearchApp(repo_path=str(tmp_path), state=state, runner=runner)

        async with app.run_test() as pilot:
            await _wait_for_condition(
                lambda: runner.finished.is_set(), timeout=5.0, msg="runner fail",
            )
            await asyncio.sleep(1.5)
            await pilot.pause()

            stats_text = _get_rendered_text(app, "stats")
            assert "FAILED" in stats_text

            # Frontier should still show items from manager step
            table: DataTable = app.query_one("#frontier-table", DataTable)
            assert table.row_count == 2


# ---------------------------------------------------------------------------
# Test: Runner exception (crash)
# ---------------------------------------------------------------------------


class TestRunnerCrash:

    @pytest.mark.asyncio
    @pytest.mark.timeout(10)
    async def test_exception_shows_crashed(self, tmp_path: Path) -> None:
        """If runner throws, TUI should show CRASHED, not freeze."""
        state = _make_state(tmp_path)

        def bad_runner() -> int:
            state.update_phase("scout")
            state.append_log({"event": "skill_started", "step": "scout"})
            time.sleep(0.1)
            raise RuntimeError("segfault in agent subprocess")

        app = ResearchApp(repo_path=str(tmp_path), state=state, runner=bad_runner)

        async with app.run_test() as pilot:
            await asyncio.sleep(2.0)
            await pilot.pause()

            stats_text = _get_rendered_text(app, "stats")
            assert "CRASHED" in stats_text, \
                f"StatsBar should show CRASHED after exception, got: {stats_text}"

            # Log should have the crash event
            events = state.tail_log(50)
            types = [e.get("event") for e in events]
            assert "session_ended" in types
            crash_ev = [e for e in events if e.get("status") == "crashed"]
            assert len(crash_ev) == 1

    @pytest.mark.asyncio
    @pytest.mark.timeout(10)
    async def test_crash_no_duplicate_messages(self, tmp_path: Path) -> None:
        """After crash, repeated polls should NOT add duplicate error lines."""
        state = _make_state(tmp_path)

        def bad_runner() -> int:
            raise ValueError("boom")

        app = ResearchApp(repo_path=str(tmp_path), state=state, runner=bad_runner)

        async with app.run_test() as pilot:
            await asyncio.sleep(3.0)  # Let several polls fire
            await pilot.pause()

            log_panel: LogPanel = app.query_one("#log", LogPanel)
            events = state.tail_log(50)
            # _seen_count should exactly match events, no extra from show_error
            assert log_panel._seen_count == len(events)


# ---------------------------------------------------------------------------
# Test: Hang detection — TUI must remain responsive
# ---------------------------------------------------------------------------


class TestHangDetection:
    """These tests FAIL if the TUI freezes for more than timeout seconds."""

    @pytest.mark.asyncio
    @pytest.mark.timeout(8)
    async def test_tui_responsive_during_runner(self, tmp_path: Path) -> None:
        """TUI should process key bindings while runner is active."""
        state = _make_state(tmp_path)

        pause_checked = threading.Event()

        def slow_runner() -> int:
            state.update_phase("scout")
            state.append_log({"event": "session_started"})
            state.append_log({"event": "skill_started", "step": "scout"})
            # Simulate a long-running agent
            for i in range(20):
                time.sleep(0.1)
                state.append_log({"event": "agent_output", "line": f"output line {i}"})
                # Check if TUI sent us a pause signal
                if state.is_paused():
                    pause_checked.set()
                    break
            state.append_log({"event": "skill_completed", "step": "scout", "exit_code": 0})
            state.update_phase("idle")
            state.append_log({"event": "session_ended", "status": "completed"})
            return 0

        app = ResearchApp(repo_path=str(tmp_path), state=state, runner=slow_runner)

        async with app.run_test() as pilot:
            # Wait a bit for runner to start
            await asyncio.sleep(0.5)
            await pilot.pause()

            # Press 'p' to pause — this tests TUI responsiveness
            await pilot.press("p")
            await pilot.pause()

            # The runner should detect the pause
            await _wait_for_condition(
                lambda: pause_checked.is_set() or state.is_paused(),
                timeout=3.0,
                msg="pause signal to reach runner",
            )
            assert state.is_paused(), "Pause action should have set paused flag"

    @pytest.mark.asyncio
    @pytest.mark.timeout(8)
    async def test_log_updates_during_active_runner(self, tmp_path: Path) -> None:
        """LogPanel should show new events while runner is still running."""
        state = _make_state(tmp_path)

        runner_started = threading.Event()

        def streaming_runner() -> int:
            state.append_log({"event": "session_started"})
            state.update_phase("scout")
            runner_started.set()
            for i in range(10):
                time.sleep(0.15)
                state.append_log({"event": "agent_output", "line": f"streaming line {i}"})
            state.update_phase("idle")
            state.append_log({"event": "session_ended", "status": "completed"})
            return 0

        app = ResearchApp(repo_path=str(tmp_path), state=state, runner=streaming_runner)

        async with app.run_test() as pilot:
            # Wait for runner to start producing output
            await _wait_for_condition(
                lambda: runner_started.is_set(), timeout=3.0, msg="runner start",
            )
            await asyncio.sleep(0.8)  # Let a few events accumulate
            await pilot.pause()

            log_panel: LogPanel = app.query_one("#log", LogPanel)
            mid_count = log_panel._seen_count
            assert mid_count > 0, "Log should have events mid-run"

            # Wait for more events
            await asyncio.sleep(1.0)
            await pilot.pause()

            final_count = log_panel._seen_count
            assert final_count > mid_count, \
                f"Log should grow during run: {mid_count} → {final_count}"


# ---------------------------------------------------------------------------
# Test: Concurrent safety — no deadlock between runner + poll
# ---------------------------------------------------------------------------


class TestConcurrentSafety:

    @pytest.mark.asyncio
    @pytest.mark.timeout(10)
    async def test_rapid_state_writes_no_deadlock(self, tmp_path: Path) -> None:
        """Runner writing state rapidly while TUI polls should not deadlock."""
        state = _make_state(tmp_path)

        def rapid_writer() -> int:
            state.append_log({"event": "session_started"})
            state.update_phase("experiment")
            # Rapid fire: 100 writes in 1 second
            for i in range(100):
                state.append_log({"event": "agent_output", "line": f"rapid {i}"})
                state.update_worker("w0", status="running", step=str(i))
                if i % 10 == 0:
                    state.save_graph({
                        "hypotheses": [{"id": f"H-{i}"}],
                        "frontier": [{"id": f"F-{i}", "priority": 0.5, "status": "pending",
                                       "description": f"item {i}"}],
                        "counters": {"hypothesis": i, "frontier": i},
                    })
                time.sleep(0.01)
            state.update_phase("idle")
            state.append_log({"event": "session_ended", "status": "completed"})
            return 0

        app = ResearchApp(repo_path=str(tmp_path), state=state, runner=rapid_writer)

        async with app.run_test() as pilot:
            # Just let it run — if it deadlocks, pytest.timeout kills it
            await asyncio.sleep(3.0)
            await pilot.pause()

            # Verify TUI is still responsive (not deadlocked)
            stats_text = _get_rendered_text(app, "stats")
            assert stats_text, "StatsBar should have content (TUI not dead)"

            log_panel: LogPanel = app.query_one("#log", LogPanel)
            assert log_panel._seen_count > 0, "Log should have events"
