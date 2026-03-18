"""Tests for the v2 TUI ResearchApp."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from open_researcher_v2.state import ResearchState
from open_researcher_v2.tui.app import ResearchApp
from open_researcher_v2.tui.widgets import (
    FrontierPanel,
    LogPanel,
    MetricChart,
    PhaseStripBar,
    StatsBar,
    WorkerPanel,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(tmp_path: Path) -> ResearchState:
    """Create a ResearchState backed by a temporary directory."""
    research_dir = tmp_path / ".research"
    research_dir.mkdir(parents=True, exist_ok=True)
    return ResearchState(research_dir)


# ---------------------------------------------------------------------------
# TestTUIAppImport
# ---------------------------------------------------------------------------


class TestTUIAppImport:
    """Verify ResearchApp can be imported."""

    def test_import(self) -> None:
        from open_researcher_v2.tui.app import ResearchApp  # noqa: F811

        assert ResearchApp is not None

    def test_is_app_subclass(self) -> None:
        from textual.app import App

        assert issubclass(ResearchApp, App)


# ---------------------------------------------------------------------------
# TestTUIAppInstantiation
# ---------------------------------------------------------------------------


class TestTUIAppInstantiation:
    """Verify ResearchApp can be created with mock and real state."""

    def test_create_with_mock_state(self) -> None:
        mock_state = MagicMock(spec=ResearchState)
        app = ResearchApp(repo_path="/tmp/repo", state=mock_state)
        assert app.repo_path == "/tmp/repo"
        assert app.state is mock_state
        assert app.runner is None

    def test_create_with_runner(self) -> None:
        mock_state = MagicMock(spec=ResearchState)
        mock_runner = MagicMock()
        app = ResearchApp(
            repo_path="/tmp/repo", state=mock_state, runner=mock_runner
        )
        assert app.runner is mock_runner

    def test_create_with_real_state(self, tmp_path: Path) -> None:
        state = _make_state(tmp_path)
        app = ResearchApp(repo_path=str(tmp_path), state=state)
        assert app.state is state

    def test_bindings(self) -> None:
        mock_state = MagicMock(spec=ResearchState)
        app = ResearchApp(repo_path="/tmp/repo", state=mock_state)
        keys = [b.key for b in app.BINDINGS]
        assert "p" in keys
        assert "r" in keys
        assert "s" in keys
        assert "q" in keys

    def test_title(self) -> None:
        mock_state = MagicMock(spec=ResearchState)
        app = ResearchApp(repo_path="/tmp/repo", state=mock_state)
        assert app.TITLE == "Open Researcher"


# ---------------------------------------------------------------------------
# TestTUIAppMount — async tests using textual's run_test
# ---------------------------------------------------------------------------


class TestTUIAppMount:
    """Test mounting and widget composition."""

    @pytest.mark.asyncio
    async def test_compose_all_widgets(self, tmp_path: Path) -> None:
        state = _make_state(tmp_path)
        app = ResearchApp(repo_path=str(tmp_path), state=state)
        async with app.run_test() as pilot:
            # All widgets should be present
            assert app.query_one("#stats", StatsBar) is not None
            assert app.query_one("#phase", PhaseStripBar) is not None
            assert app.query_one("#frontier", FrontierPanel) is not None
            assert app.query_one("#workers", WorkerPanel) is not None
            assert app.query_one("#chart", MetricChart) is not None
            assert app.query_one("#log", LogPanel) is not None

    @pytest.mark.asyncio
    async def test_poll_with_empty_state(self, tmp_path: Path) -> None:
        """Polling with empty state files should not raise."""
        state = _make_state(tmp_path)
        app = ResearchApp(repo_path=str(tmp_path), state=state)
        async with app.run_test() as pilot:
            # Manually trigger poll
            app._poll_state()

    @pytest.mark.asyncio
    async def test_poll_with_data(self, tmp_path: Path) -> None:
        """Polling with populated state files updates widgets."""
        state = _make_state(tmp_path)
        # Write some activity
        state.save_activity({
            "phase": "manager",
            "round": 2,
            "workers": [
                {"id": "w0", "status": "running", "gpu": "0", "frontier_id": "F-1"},
            ],
            "control": {"paused": False, "skip_current": False},
        })
        # Write a log entry
        state.append_log({"type": "skill_started", "message": "Running scout"})
        # Write a result
        state.append_result({
            "worker": "w0",
            "frontier_id": "F-1",
            "status": "keep",
            "metric": "accuracy",
            "value": "0.91",
            "description": "test result",
        })

        app = ResearchApp(repo_path=str(tmp_path), state=state)
        async with app.run_test() as pilot:
            app._poll_state()
            stats: StatsBar = app.query_one("#stats", StatsBar)
            assert "manager" in str(stats.content)

    @pytest.mark.asyncio
    async def test_poll_never_crashes(self, tmp_path: Path) -> None:
        """Polling should swallow exceptions."""
        mock_state = MagicMock(spec=ResearchState)
        mock_state.summary.side_effect = RuntimeError("disk fail")
        app = ResearchApp(repo_path=str(tmp_path), state=mock_state)
        async with app.run_test() as pilot:
            # Should not raise
            app._poll_state()


# ---------------------------------------------------------------------------
# TestTUIAppActions
# ---------------------------------------------------------------------------


class TestTUIAppActions:
    """Test action methods (pause/resume/skip)."""

    @pytest.mark.asyncio
    async def test_action_pause(self, tmp_path: Path) -> None:
        state = _make_state(tmp_path)
        app = ResearchApp(repo_path=str(tmp_path), state=state)
        async with app.run_test() as pilot:
            app.action_pause()
            assert state.is_paused() is True

    @pytest.mark.asyncio
    async def test_action_resume(self, tmp_path: Path) -> None:
        state = _make_state(tmp_path)
        state.set_paused(True)
        app = ResearchApp(repo_path=str(tmp_path), state=state)
        async with app.run_test() as pilot:
            app.action_resume()
            assert state.is_paused() is False

    @pytest.mark.asyncio
    async def test_action_skip(self, tmp_path: Path) -> None:
        state = _make_state(tmp_path)
        app = ResearchApp(repo_path=str(tmp_path), state=state)
        async with app.run_test() as pilot:
            app.action_skip()
            activity = state.load_activity()
            assert activity["control"]["skip_current"] is True

    @pytest.mark.asyncio
    async def test_action_errors_swallowed(self, tmp_path: Path) -> None:
        """Actions should not crash if state operations fail."""
        mock_state = MagicMock(spec=ResearchState)
        mock_state.set_paused.side_effect = OSError("disk fail")
        mock_state.set_skip_current.side_effect = OSError("disk fail")
        app = ResearchApp(repo_path=str(tmp_path), state=mock_state)
        async with app.run_test() as pilot:
            # None of these should raise
            app.action_pause()
            app.action_resume()
            app.action_skip()


# ---------------------------------------------------------------------------
# TestTUIAppRunner
# ---------------------------------------------------------------------------


class TestTUIAppRunner:
    """Test the runner thread integration."""

    @pytest.mark.asyncio
    async def test_runner_started_on_mount(self, tmp_path: Path) -> None:
        """Runner should be invoked in a daemon thread."""
        called = []

        def fake_runner() -> None:
            called.append(True)

        state = _make_state(tmp_path)
        app = ResearchApp(
            repo_path=str(tmp_path), state=state, runner=fake_runner
        )
        async with app.run_test() as pilot:
            # Give thread a moment to execute
            import asyncio
            await asyncio.sleep(0.2)
            assert len(called) >= 1

    @pytest.mark.asyncio
    async def test_runner_exception_swallowed(self, tmp_path: Path) -> None:
        """Runner exceptions should not crash the TUI."""

        def bad_runner() -> None:
            raise RuntimeError("runner exploded")

        state = _make_state(tmp_path)
        app = ResearchApp(
            repo_path=str(tmp_path), state=state, runner=bad_runner
        )
        async with app.run_test() as pilot:
            import asyncio
            await asyncio.sleep(0.2)
            # App should still be running
            assert app.is_running

    @pytest.mark.asyncio
    async def test_no_runner_thread_when_none(self, tmp_path: Path) -> None:
        """No thread should be created when runner is None."""
        state = _make_state(tmp_path)
        app = ResearchApp(repo_path=str(tmp_path), state=state)
        async with app.run_test() as pilot:
            assert app._runner_thread is None


# ---------------------------------------------------------------------------
# TestReviewDetection
# ---------------------------------------------------------------------------


class TestReviewDetection:
    """Test review modal wiring and detection."""

    def test_review_shown_flag_default(self, tmp_path: Path) -> None:
        state = _make_state(tmp_path)
        app = ResearchApp(repo_path=str(tmp_path), state=state, runner=None)
        assert app._review_shown is False

    def test_action_quit_clears_review(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        state = _make_state(tmp_path)
        state.set_awaiting_review({"type": "test", "requested_at": "2026-03-19T14:00:00Z"})
        the_app = ResearchApp(repo_path=str(tmp_path), state=state, runner=None)
        with patch.object(the_app.__class__.__bases__[0], "action_quit"):
            the_app.action_quit()
        assert state.get_awaiting_review() is None

    def test_make_review_screen_returns_correct_type(self, tmp_path: Path) -> None:
        from open_researcher_v2.tui.modals.hypothesis import HypothesisReviewScreen

        state = _make_state(tmp_path)
        the_app = ResearchApp(repo_path=str(tmp_path), state=state, runner=None)
        screen = the_app._make_review_screen({"type": "hypothesis_review", "requested_at": "now"})
        assert isinstance(screen, HypothesisReviewScreen)

    def test_make_review_screen_unknown_type_clears(self, tmp_path: Path) -> None:
        state = _make_state(tmp_path)
        state.set_awaiting_review({"type": "bogus", "requested_at": "now"})
        the_app = ResearchApp(repo_path=str(tmp_path), state=state, runner=None)
        with pytest.raises(ValueError):
            the_app._make_review_screen({"type": "bogus"})
        assert state.get_awaiting_review() is None
