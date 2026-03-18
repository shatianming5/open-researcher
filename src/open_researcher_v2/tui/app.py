"""TUI main application for Open-Researcher v2.

Provides :class:`ResearchApp`, a Textual application that polls
:class:`ResearchState` every second and pushes updates to the widgets.
An optional *runner* callable is started in a daemon thread so the TUI
can monitor a live research session.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Header, TabbedContent, TabPane

from open_researcher_v2.state import ResearchState
from open_researcher_v2.tui.modals.direction import DirectionConfirmScreen
from open_researcher_v2.tui.modals.hypothesis import HypothesisReviewScreen
from open_researcher_v2.tui.modals.frontier import FrontierReviewScreen
from open_researcher_v2.tui.modals.result import ResultReviewScreen
from open_researcher_v2.tui.modals.goal_edit import GoalEditScreen
from open_researcher_v2.tui.modals.inject import InjectIdeaScreen
from open_researcher_v2.tui.widgets import (
    FrontierPanel,
    LogPanel,
    MetricChart,
    PhaseStripBar,
    StatsBar,
    WorkerPanel,
)

# ---------------------------------------------------------------------------
# ResearchApp
# ---------------------------------------------------------------------------


class ResearchApp(App):
    """Polling-based TUI for monitoring and controlling a research session.

    Parameters
    ----------
    repo_path:
        Path to the repository root (informational only).
    state:
        A :class:`ResearchState` instance for reading/writing state files.
    runner:
        An optional callable to execute in a daemon thread.  Typically
        this is the orchestration loop that drives the research.
    """

    CSS_PATH = "styles.css"
    TITLE = "Open Researcher"

    BINDINGS = [
        Binding("p", "pause", "Pause"),
        Binding("r", "resume", "Resume"),
        Binding("s", "skip", "Skip"),
        Binding("g", "edit_goal", "Goal"),
        Binding("i", "inject_idea", "Inject"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        repo_path: str,
        state: ResearchState,
        runner: Callable[[], Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.repo_path = repo_path
        self.state = state
        self.runner = runner
        self._runner_thread: threading.Thread | None = None
        self._review_shown = False

    # -- layout -------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        yield StatsBar(id="stats")
        yield PhaseStripBar(id="phase")
        with TabbedContent():
            with TabPane("Execution", id="tab-exec"):
                with Horizontal():
                    yield FrontierPanel(id="frontier")
                    yield WorkerPanel(id="workers")
            with TabPane("Metrics", id="tab-metrics"):
                yield MetricChart(id="chart")
            with TabPane("Logs", id="tab-logs"):
                yield LogPanel(id="log")
        yield Footer()

    # -- lifecycle ----------------------------------------------------------

    def on_mount(self) -> None:
        """Start polling and optionally the runner thread."""
        self.set_interval(1.0, self._poll_state)
        if self.runner is not None:
            self._runner_thread = threading.Thread(
                target=self._run_runner, daemon=True
            )
            self._runner_thread.start()

    def _run_runner(self) -> None:
        """Execute the runner callable; log errors to state on failure."""
        try:
            if self.runner is not None:
                self.runner()
        except Exception as exc:
            try:
                self.state.append_log({"event": "runner_error", "line": str(exc)})
            except Exception:
                pass

    # -- polling ------------------------------------------------------------

    def _poll_state(self) -> None:
        """Read state files and push data to widgets.

        All exceptions are caught to ensure polling never crashes the TUI.
        """
        try:
            summary = self.state.summary()

            stats: StatsBar = self.query_one("#stats", StatsBar)
            stats.update_data(summary)

            phase_bar: PhaseStripBar = self.query_one("#phase", PhaseStripBar)
            phase_bar.update_phase(summary.get("phase", "idle"))

            # Frontier
            graph = self.state.load_graph()
            frontier: FrontierPanel = self.query_one("#frontier", FrontierPanel)
            frontier.update_data(graph.get("frontier", []))

            # Workers
            workers: WorkerPanel = self.query_one("#workers", WorkerPanel)
            workers.update_data(summary.get("workers", []))

            # Logs
            events = self.state.tail_log(50)
            log_panel: LogPanel = self.query_one("#log", LogPanel)
            log_panel.update_data(events)

            # Metrics
            results = self.state.load_results()
            chart: MetricChart = self.query_one("#chart", MetricChart)
            chart.update_data(results)

            # Check for pending review
            review = summary.get("awaiting_review")
            if review and not self._review_shown:
                self._review_shown = True
                try:
                    screen = self._make_review_screen(review)
                    self.push_screen(screen, callback=self._on_review_done)
                except Exception:
                    self._review_shown = False
        except Exception:
            # Never let a polling error crash the TUI
            pass

    # -- actions ------------------------------------------------------------

    def action_pause(self) -> None:
        """Pause research by setting the paused flag."""
        try:
            self.state.set_paused(True)
        except Exception:
            pass

    def action_resume(self) -> None:
        """Resume research by clearing the paused flag."""
        try:
            self.state.set_paused(False)
        except Exception:
            pass

    def action_skip(self) -> None:
        """Request skipping the current experiment."""
        try:
            self.state.set_skip_current(True)
        except Exception:
            pass

    def _make_review_screen(self, review: dict):
        """Create the appropriate review screen for the review type."""
        rtype = review.get("type", "")
        if rtype == "direction_confirm":
            return DirectionConfirmScreen(state=self.state, review_request=review)
        if rtype == "hypothesis_review":
            return HypothesisReviewScreen(state=self.state, review_request=review)
        if rtype == "frontier_review":
            return FrontierReviewScreen(state=self.state, review_request=review)
        if rtype == "result_review":
            return ResultReviewScreen(state=self.state, review_request=review)
        self.state.clear_awaiting_review()
        raise ValueError(f"Unknown review type: {rtype}")

    def _on_review_done(self, result) -> None:
        self._review_shown = False

    def action_edit_goal(self) -> None:
        """Open goal edit modal."""
        try:
            self.push_screen(GoalEditScreen(state=self.state))
        except Exception:
            pass

    def action_inject_idea(self) -> None:
        """Open inject idea modal."""
        try:
            self.push_screen(InjectIdeaScreen(state=self.state))
        except Exception:
            pass

    def action_quit(self) -> None:
        """Quit TUI, cleaning up any pending review."""
        if self.state.get_awaiting_review():
            self.state.clear_awaiting_review()
            self.state.append_log({"event": "review_skipped", "review_type": "quit"})
        self._review_shown = False
        super().action_quit()
