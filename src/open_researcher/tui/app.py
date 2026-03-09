"""Main Textual application for Open Researcher."""

import json
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import ScrollableContainer
from textual.css.query import NoMatches
from textual.widgets import RichLog, TabbedContent, TabPane

from open_researcher.activity import ActivityMonitor
from open_researcher.idea_pool import IdeaPool
from open_researcher.status_cmd import parse_research_state
from open_researcher.tui.modals import AddIdeaModal, GPUStatusModal, LogScreen
from open_researcher.tui.widgets import (
    DocViewer,
    ExperimentStatusPanel,
    HotkeyBar,
    IdeaListPanel,
    MetricChart,
    RecentExperiments,
    StatsBar,
)


class ResearchApp(App):
    """Interactive TUI for monitoring and controlling Open Researcher agents."""

    CSS_PATH = "styles.css"

    BINDINGS = [
        ("1", "switch_tab('tab-overview')", "Overview"),
        ("2", "switch_tab('tab-ideas')", "Ideas"),
        ("3", "switch_tab('tab-charts')", "Charts"),
        ("4", "switch_tab('tab-logs')", "Logs"),
        ("5", "switch_tab('tab-docs')", "Docs"),
        ("p", "pause", "Pause"),
        ("r", "resume", "Resume"),
        ("s", "skip", "Skip idea"),
        ("a", "add_idea", "Add idea"),
        ("g", "gpu_status", "GPU status"),
        ("l", "view_log", "View log"),
        ("q", "quit_app", "Quit"),
    ]

    def __init__(self, repo_path: Path, multi: bool = False, on_ready=None):
        super().__init__()
        self.repo_path = repo_path
        self.research_dir = repo_path / ".research"
        self.multi = multi
        self.pool = IdeaPool(self.research_dir / "idea_pool.json")
        self.activity = ActivityMonitor(self.research_dir)
        self._on_ready = on_ready

    def compose(self) -> ComposeResult:
        yield StatsBar(id="stats-bar")
        with TabbedContent(id="tabs"):
            with TabPane("Overview", id="tab-overview"):
                yield ExperimentStatusPanel(id="exp-status")
                yield RecentExperiments(id="recent-exp")
            with TabPane("Ideas", id="tab-ideas"):
                with ScrollableContainer(id="idea-scroll"):
                    yield IdeaListPanel(id="idea-list")
            with TabPane("Charts", id="tab-charts"):
                yield MetricChart(id="metric-chart")
            with TabPane("Logs", id="tab-logs"):
                yield RichLog(id="agent-log", wrap=True, markup=True)
            with TabPane("Docs", id="tab-docs"):
                yield DocViewer(research_dir=self.research_dir, id="doc-viewer")
        yield HotkeyBar(id="hotkey-bar")

    def on_mount(self) -> None:
        self.set_interval(1.0, self._refresh_data)
        # Start agent threads AFTER event loop is running
        # to avoid call_from_thread failures during startup
        if self._on_ready:
            self._on_ready()

    def action_switch_tab(self, tab_id: str) -> None:
        try:
            self.query_one("#tabs", TabbedContent).active = tab_id
        except Exception:
            pass

    def _refresh_data(self) -> None:
        # Refresh stats bar
        state = None
        try:
            state = parse_research_state(self.repo_path)
            self.query_one("#stats-bar", StatsBar).update_stats(state)
        except (json.JSONDecodeError, OSError, KeyError, NoMatches):
            pass

        # Refresh idea list + experiment status
        try:
            ideas = self.pool.all_ideas()
            self.query_one("#idea-list", IdeaListPanel).update_ideas(ideas)

            # Calculate progress
            completed = sum(1 for i in ideas if i["status"] in ("done", "skipped"))
            total = len(ideas)
        except (json.JSONDecodeError, OSError, KeyError, NoMatches):
            ideas = []
            completed = 0
            total = 0

        # Refresh experiment status
        try:
            exp_act = self.activity.get("experiment_agent")
            idea_act = self.activity.get("idea_agent")
            active = (
                exp_act
                if exp_act and exp_act.get("status") not in (None, "idle")
                else idea_act
            )
            self.query_one("#exp-status", ExperimentStatusPanel).update_status(
                active, completed, total
            )
        except (json.JSONDecodeError, OSError, KeyError, NoMatches):
            pass

        # Refresh recent experiments and metric chart from results.tsv
        try:
            from open_researcher.results_cmd import load_results

            rows = load_results(self.repo_path)
            try:
                self.query_one("#recent-exp", RecentExperiments).update_results(rows)
            except NoMatches:
                pass
            try:
                metric_name = (
                    state.get("primary_metric", "metric")
                    if state
                    else "metric"
                )
                self.query_one("#metric-chart", MetricChart).update_data(
                    rows, metric_name
                )
            except NoMatches:
                pass
        except Exception:
            pass

    def _read_control(self) -> dict:
        ctrl_path = self.research_dir / "control.json"
        if ctrl_path.exists():
            try:
                return json.loads(ctrl_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {"paused": False, "skip_current": False}

    def _write_control(self, data: dict) -> None:
        ctrl_path = self.research_dir / "control.json"
        ctrl_path.write_text(json.dumps(data, indent=2))

    def action_pause(self) -> None:
        ctrl = self._read_control()
        ctrl["paused"] = True
        self._write_control(ctrl)
        self.notify("Experiment paused")

    def action_resume(self) -> None:
        ctrl = self._read_control()
        ctrl["paused"] = False
        self._write_control(ctrl)
        self.notify("Experiment resumed")

    def action_skip(self) -> None:
        ctrl = self._read_control()
        ctrl["skip_current"] = True
        self._write_control(ctrl)
        self.notify("Skipping current idea")

    def action_add_idea(self) -> None:
        def on_result(result: dict | None) -> None:
            if result:
                self.pool.add(
                    result["description"],
                    source="user",
                    category=result["category"],
                    priority=result["priority"],
                )
                self.notify(f"Added idea: {result['description'][:40]}")

        self.push_screen(AddIdeaModal(), on_result)

    def action_gpu_status(self) -> None:
        gpu_path = self.research_dir / "gpu_status.json"
        gpus = []
        if gpu_path.exists():
            try:
                gpus = json.loads(gpu_path.read_text()).get("gpus", [])
            except (json.JSONDecodeError, OSError):
                pass
        self.push_screen(GPUStatusModal(gpus))

    def action_view_log(self) -> None:
        log_path = str(self.research_dir / "run.log")
        self.push_screen(LogScreen(log_path))

    def action_quit_app(self) -> None:
        self.exit()

    def append_log(self, line: str) -> None:
        """Thread-safe: append a line to the unified log panel."""
        self.call_from_thread(self._do_append_log, line)

    def _do_append_log(self, line: str) -> None:
        try:
            self.query_one("#agent-log", RichLog).write(line)
        except NoMatches:
            pass

    # Keep old names as aliases for backward compatibility
    append_idea_log = append_log
    append_exp_log = append_log
