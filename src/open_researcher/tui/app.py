"""Main Textual application for Open Researcher."""

import json
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import RichLog, Static

from open_researcher.activity import ActivityMonitor
from open_researcher.idea_pool import IdeaPool
from open_researcher.status_cmd import parse_research_state
from open_researcher.tui.modals import AddIdeaModal, GPUStatusModal, LogScreen
from open_researcher.tui.widgets import (
    AgentStatusWidget,
    HotkeyBar,
    IdeaPoolPanel,
    StatsBar,
    WorkerStatusPanel,
)


class ResearchApp(App):
    """Interactive TUI for monitoring and controlling Open Researcher agents."""

    CSS_PATH = "styles.css"

    BINDINGS = [
        ("p", "pause", "Pause"),
        ("r", "resume", "Resume"),
        ("s", "skip", "Skip idea"),
        ("a", "add_idea", "Add idea"),
        ("g", "gpu_status", "GPU status"),
        ("l", "view_log", "View log"),
        ("q", "quit_app", "Quit"),
    ]

    def __init__(self, repo_path: Path, multi: bool = False):
        super().__init__()
        self.repo_path = repo_path
        self.research_dir = repo_path / ".research"
        self.multi = multi
        self.pool = IdeaPool(self.research_dir / "idea_pool.json")
        self.activity = ActivityMonitor(self.research_dir)

    def compose(self) -> ComposeResult:
        yield StatsBar(id="stats-bar")
        yield IdeaPoolPanel(id="idea-pool")
        with Horizontal(id="agent-panels"):
            with Vertical(id="idea-agent-section"):
                yield Static("Idea Agent", classes="panel-title")
                yield AgentStatusWidget(id="idea-status")
                yield RichLog(id="idea-log", wrap=True, markup=False)
            with Vertical(id="exp-agent-section"):
                yield Static("Experiment Master", classes="panel-title")
                yield WorkerStatusPanel(id="worker-status")
                yield RichLog(id="exp-log", wrap=True, markup=False)
        yield HotkeyBar(id="hotkey-bar")

    def on_mount(self) -> None:
        self.set_interval(1.0, self._refresh_data)

    def _refresh_data(self) -> None:
        # Refresh stats bar
        try:
            state = parse_research_state(self.repo_path)
            self.query_one("#stats-bar", StatsBar).update_stats(state)
        except (json.JSONDecodeError, OSError, KeyError, NoMatches):
            pass

        # Refresh idea pool with worker GPU info
        try:
            ideas = self.pool.all_ideas()
            summary = self.pool.summary()
            exp_master = self.activity.get("experiment_master")
            workers = exp_master.get("workers", []) if exp_master else []
            self.query_one("#idea-pool", IdeaPoolPanel).update_ideas(ideas, summary, workers)
        except (json.JSONDecodeError, OSError, KeyError, NoMatches):
            pass

        # Refresh idea agent status
        try:
            idea_act = self.activity.get("idea_agent")
            self.query_one("#idea-status", AgentStatusWidget).update_status(idea_act)
        except (json.JSONDecodeError, OSError, KeyError, NoMatches):
            pass

        # Refresh worker status panel
        try:
            exp_master = self.activity.get("experiment_master")
            if exp_master:
                workers = exp_master.get("workers", [])
                gpu_total = exp_master.get("gpu_total", 0)
                self.query_one("#worker-status", WorkerStatusPanel).update_workers(workers, gpu_total)
        except (json.JSONDecodeError, OSError, KeyError, NoMatches):
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
        if self.multi:
            # In multi mode, show both logs concatenated
            log_path = str(self.research_dir / "experiment_agent.log")
        else:
            log_path = str(self.research_dir / "run.log")
        self.push_screen(LogScreen(log_path))

    def action_quit_app(self) -> None:
        self.exit()

    def append_idea_log(self, line: str) -> None:
        """Thread-safe: append a line to the Idea Agent log panel."""
        self.call_from_thread(self._do_append_idea_log, line)

    def _do_append_idea_log(self, line: str) -> None:
        try:
            self.query_one("#idea-log", RichLog).write(line)
        except NoMatches:
            pass

    def append_exp_log(self, line: str) -> None:
        """Thread-safe: append a line to the Experiment Master log panel."""
        self.call_from_thread(self._do_append_exp_log, line)

    def _do_append_exp_log(self, line: str) -> None:
        try:
            self.query_one("#exp-log", RichLog).write(line)
        except NoMatches:
            pass
