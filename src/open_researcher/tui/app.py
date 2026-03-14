"""Main Textual application for the research-v1 command center."""

import json
import logging
import time
from pathlib import Path
from typing import Literal

from textual.app import App, ComposeResult
from textual.containers import Container, ScrollableContainer, Vertical
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.theme import Theme
from textual.widgets import RichLog, TabbedContent, TabPane

from open_researcher.activity import ActivityMonitor
from open_researcher.control_plane import issue_control_command, read_control
from open_researcher.idea_pool import IdeaBacklog
from open_researcher.status_cmd import parse_research_state
from open_researcher.tui.modals import GPUStatusModal, LogScreen
from open_researcher.tui.view_model import DashboardState, RoleStatus, build_dashboard_state, build_docs_workbench
from open_researcher.tui.widgets import (
    BootstrapStatusPanel,
    DocsSidebarPanel,
    DocViewer,
    ExecutionSummaryPanel,
    ExperimentStatusPanel,
    FrontierDetailPanel,
    FrontierFocusPanel,
    HotkeyBar,
    LineageTimelinePanel,
    MetricChart,
    PhaseStripBar,
    RecentExperiments,
    ResearchGraphSummaryPanel,
    RoleActivityPanel,
    SessionChromeBar,
    StatsBar,
    TraceBanner,
)

logger = logging.getLogger(__name__)


class ResearchApp(App):
    """Interactive TUI for monitoring and controlling research-v1 sessions."""

    CSS_PATH = "styles.css"

    BINDINGS = [
        ("1", "switch_tab('tab-command')", "Command"),
        ("2", "switch_tab('tab-execution')", "Execution"),
        ("3", "switch_tab('tab-logs')", "Logs"),
        ("4", "switch_tab('tab-docs')", "Docs"),
        ("p", "pause", "Pause"),
        ("r", "resume", "Resume"),
        ("s", "skip", "Skip frontier"),
        ("S", "clear_skip", "Cancel skip"),
        ("g", "gpu_status", "GPU status"),
        ("l", "view_log", "View log"),
        ("n", "next_doc", "Next doc"),
        ("b", "prev_doc", "Prev doc"),
        ("q", "quit_app", "Quit"),
    ]

    app_phase: reactive[str] = reactive("experimenting")
    trace_banner_text: reactive[str] = reactive("")
    selected_frontier_id: reactive[str] = reactive("")

    def __init__(self, repo_path: Path, on_ready=None, initial_phase: str = "experimenting"):
        super().__init__()
        self.repo_path = repo_path
        self.research_dir = repo_path / ".research"
        self.pool = IdeaBacklog(self.research_dir / "idea_pool.json")
        self.activity = ActivityMonitor(self.research_dir)
        self._on_ready = on_ready
        self.app_phase = initial_phase
        self._state_cache: dict | None = None
        self._state_cache_time: float = 0.0
        self._dashboard_cache: DashboardState | None = None
        self._progress_total_high_water: int = 0

    def compose(self) -> ComposeResult:
        yield StatsBar(id="stats-bar")
        yield PhaseStripBar(id="phase-strip")
        with TabbedContent(id="tabs"):
            with TabPane("Command", id="tab-command"):
                yield SessionChromeBar(id="session-chrome", classes="hero-card")
                with Container(id="command-main"):
                    with Vertical(id="command-left", classes="column"):
                        yield RoleActivityPanel(id="role-activity", classes="panel-card")
                        yield BootstrapStatusPanel(id="bootstrap-status", classes="panel-card")
                        yield ResearchGraphSummaryPanel(id="graph-summary", classes="panel-card")
                        yield LineageTimelinePanel(id="lineage-timeline", classes="panel-card")
                    with Container(id="command-right", classes="column"):
                        with Container(id="frontier-main"):
                            with ScrollableContainer(id="frontier-scroll", classes="panel-card"):
                                yield FrontierFocusPanel(id="frontier-focus")
                            yield FrontierDetailPanel(id="frontier-detail", classes="panel-card")
            with TabPane("Execution", id="tab-execution"):
                yield ExecutionSummaryPanel(id="execution-summary", classes="hero-card")
                with Container(id="execution-main"):
                    yield MetricChart(id="metric-chart", classes="panel-card")
                    with Vertical(id="execution-side", classes="column"):
                        yield ExperimentStatusPanel(id="exp-status", classes="panel-card")
                        yield RecentExperiments(id="recent-exp", classes="panel-card")
            with TabPane("Logs", id="tab-logs"):
                yield TraceBanner(id="trace-banner", classes="trace-card")
                yield RichLog(id="agent-log", wrap=True, markup=True)
            with TabPane("Docs", id="tab-docs"):
                with Container(id="docs-main"):
                    yield DocsSidebarPanel(id="docs-sidebar", classes="panel-card")
                    yield DocViewer(research_dir=self.research_dir, id="doc-viewer")
        yield HotkeyBar(id="hotkey-bar")

    _UI_STATE_FILE = ".tui_state.json"

    def on_mount(self) -> None:
        self.register_theme(
            Theme(
                name="research-command-dark",
                primary="#8bd5ff",
                secondary="#a6da95",
                foreground="#d7e1f3",
                background="#060d15",
                surface="#08111a",
                panel="#101a26",
                warning="#f4bf75",
                error="#ff7b72",
                success="#7dd4b0",
                accent="#c6a0f6",
                dark=True,
            )
        )
        self.theme = "research-command-dark"
        self._sync_layout_mode()
        self._restore_ui_state()
        self.set_interval(1.0, self._refresh_data)
        if self._on_ready:
            self._on_ready()

    def on_resize(self, _) -> None:
        if hasattr(self, "_resize_timer") and self._resize_timer is not None:
            self._resize_timer.stop()
        self._resize_timer = self.set_timer(0.15, self._sync_layout_mode)

    def _sync_layout_mode(self) -> None:
        width = self.size.width
        if width >= 140:
            mode = "layout-wide"
        elif width >= 100:
            mode = "layout-medium"
        else:
            mode = "layout-compact"
        self.remove_class("layout-wide", "layout-medium", "layout-compact")
        self.add_class(mode)

    def watch_app_phase(self, _old_phase: str, new_phase: str) -> None:
        if not self._running:
            return
        self._refresh_data()
        # Immediately update hotkey bar so available keys are accurate
        try:
            active_tab = ""
            try:
                active_tab = self.query_one("#tabs", TabbedContent).active
            except NoMatches:
                pass
            paused = self._dashboard_cache.session.paused if self._dashboard_cache else False
            self.query_one("#hotkey-bar", HotkeyBar).update_state(
                paused=paused, phase=new_phase, active_tab=active_tab,
            )
        except NoMatches:
            pass

    def watch_trace_banner_text(self, _old_text: str, new_text: str) -> None:
        try:
            self.query_one("#trace-banner", TraceBanner).update_trace(new_text)
        except NoMatches:
            logger.debug("Trace banner not mounted yet", exc_info=True)

    _TAB_FOCUS_TARGETS: dict[str, str] = {
        "tab-command": "#frontier-focus #frontier-options",
        "tab-execution": "#metric-chart",
        "tab-logs": "#agent-log",
        "tab-docs": "#docs-sidebar #docs-options",
    }

    def _save_ui_state(self) -> None:
        """Schedule a debounced UI state save (avoids disk writes on every highlight)."""
        if hasattr(self, "_ui_save_timer") and self._ui_save_timer is not None:
            self._ui_save_timer.stop()
        self._ui_save_timer = self.set_timer(0.5, self._do_save_ui_state)

    def _do_save_ui_state(self) -> None:
        state_path = self.research_dir / self._UI_STATE_FILE
        try:
            active_tab = self.query_one("#tabs", TabbedContent).active
        except NoMatches:
            active_tab = "tab-command"
        state = {"active_tab": active_tab, "selected_frontier_id": self.selected_frontier_id}
        try:
            state_path.write_text(json.dumps(state), encoding="utf-8")
        except OSError:
            pass

    def _restore_ui_state(self) -> None:
        state_path = self.research_dir / self._UI_STATE_FILE
        if not state_path.exists():
            return
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            tab = state.get("active_tab", "")
            if tab:
                self.query_one("#tabs", TabbedContent).active = tab
            frontier = state.get("selected_frontier_id", "")
            if frontier:
                self.selected_frontier_id = frontier
        except (json.JSONDecodeError, OSError, NoMatches):
            pass

    def action_switch_tab(self, tab_id: str) -> None:
        try:
            self.query_one("#tabs", TabbedContent).active = tab_id
        except NoMatches:
            logger.debug("Tab %s not found", tab_id)
            return
        self._save_ui_state()
        # Immediately update hotkey bar so available keys are accurate
        try:
            paused = self._dashboard_cache.session.paused if self._dashboard_cache else False
            self.query_one("#hotkey-bar", HotkeyBar).update_state(
                paused=paused, phase=self.app_phase, active_tab=tab_id,
            )
        except NoMatches:
            pass
        # Transfer focus to the primary interactive widget in the target tab
        target = self._TAB_FOCUS_TARGETS.get(tab_id)
        if target:
            self.set_timer(0.1, lambda: self._focus_tab_target(target))

    def _focus_tab_target(self, selector: str) -> None:
        try:
            widget = self.query_one(selector)
            widget.focus()
        except (NoMatches, Exception):
            logger.debug("Could not focus %s", selector, exc_info=True)

    async def on_docs_sidebar_panel_doc_requested(self, event: DocsSidebarPanel.DocRequested) -> None:
        try:
            doc_viewer = self.query_one("#doc-viewer", DocViewer)
            await doc_viewer.select_doc(event.filename)
            docs_state = build_docs_workbench(
                self.research_dir,
                current_file=doc_viewer.current_file,
                doc_files=DocViewer.DOC_FILES,
                dynamic_files=DocViewer.DYNAMIC_FILES,
            )
            self.query_one("#docs-sidebar", DocsSidebarPanel).update_docs(
                docs_state.items,
                current_file=docs_state.current_file,
            )
        except NoMatches:
            logger.debug("Doc viewer not mounted", exc_info=True)

    def on_projected_backlog_panel_frontier_requested(self, event: FrontierFocusPanel.FrontierRequested) -> None:
        # sync_list=False: the OptionList already has the correct highlight
        # from the user's own navigation — no need to set it again, which
        # would create a highlight→sync→highlight feedback loop and flicker.
        self._apply_frontier_selection(event.frontier_id, sync_list=False)

    def _apply_frontier_selection(self, frontier_id: str, *, sync_list: bool = True) -> None:
        self.selected_frontier_id = str(frontier_id or "").strip()
        self._save_ui_state()
        if not self.selected_frontier_id or self._dashboard_cache is None:
            return
        try:
            self.query_one("#frontier-detail", FrontierDetailPanel).update_detail(
                self._dashboard_cache.frontier_details.get(self.selected_frontier_id)
            )
            if sync_list:
                self.query_one("#frontier-focus", FrontierFocusPanel).sync_selection(self.selected_frontier_id)
        except NoMatches:
            logger.debug("Frontier detail widgets not mounted", exc_info=True)

    def _refresh_data(self) -> None:
        if not self._running:
            return
        self.run_worker(self._bg_gather_data, thread=True, exclusive=True, group="refresh")

    def _bg_gather_data(self) -> None:
        _data_errors: list[str] = []
        try:
            control = self._read_control()
        except Exception:
            logger.debug("Error reading control state", exc_info=True)
            control = {"paused": False, "skip_current": False}
            _data_errors.append("control")

        now = time.monotonic()
        if now - self._state_cache_time > 2.0 or self._state_cache is None:
            try:
                self._state_cache = parse_research_state(self.repo_path)
                self._state_cache_time = now
            except Exception:
                logger.warning("Error parsing research state", exc_info=True)
                _data_errors.append("state")
        state = self._state_cache or {}

        ideas: list[dict] = []
        try:
            ideas = self.pool.all_ideas()
        except Exception:
            logger.debug("Error reading idea pool", exc_info=True)

        activities: dict = {}
        try:
            activities = self.activity.get_all()
        except Exception:
            logger.debug("Error reading activity", exc_info=True)

        rows: list[dict] = []
        try:
            from open_researcher.results_cmd import load_results

            rows = load_results(self.repo_path)
        except Exception:
            logger.debug("Error loading results", exc_info=True)

        dashboard = build_dashboard_state(
            self.repo_path,
            state=state,
            ideas=ideas,
            activities=activities,
            rows=rows,
            control=control,
            trace_banner=self.trace_banner_text,
        )

        try:
            self.call_from_thread(self._apply_refresh_data, dashboard, state, rows, _data_errors)
        except RuntimeError:
            pass

    def _apply_refresh_data(
        self,
        dashboard: DashboardState,
        state: dict,
        rows: list[dict],
        data_errors: list[str] | None = None,
    ) -> None:
        self._dashboard_cache = dashboard
        try:
            self.query_one("#stats-bar", StatsBar).update_stats(
                state,
                phase=self.app_phase,
                paused=dashboard.session.paused,
                data_errors=data_errors or [],
                tokens_used=dashboard.session.tokens_used,
                token_budget=dashboard.session.token_budget,
                estimated_cost=dashboard.session.estimated_cost,
            )
        except NoMatches:
            logger.debug("Error refreshing stats bar", exc_info=True)

        try:
            self.query_one("#phase-strip", PhaseStripBar).update_phase(
                self.app_phase, paused=dashboard.session.paused
            )
        except NoMatches:
            logger.debug("Error refreshing phase strip", exc_info=True)

        # --- Detect active role & progress (shared by ActivityBar + ExperimentStatus) ---
        _active_role: RoleStatus | None = None
        _role_label = "Experiment Agent"
        for _r in [dashboard.roles[2], dashboard.roles[0], dashboard.roles[1]]:
            if _r.status != "idle":
                _active_role = _r
                _role_label = _r.label
                break
        _completed = dashboard.session.keep + dashboard.session.discard + dashboard.session.crash
        _raw_total = max(
            _completed + dashboard.graph.frontier_runnable,
            len(rows),
            len(dashboard.frontiers),
        )
        self._progress_total_high_water = max(self._progress_total_high_water, _raw_total)
        _total = self._progress_total_high_water

        try:
            self.query_one("#session-chrome", SessionChromeBar).update_chrome(
                dashboard.session,
                active_role=_active_role,
                phase=self.app_phase,
                completed=_completed,
                total=_total,
            )
        except NoMatches:
            logger.debug("Error refreshing session chrome", exc_info=True)

        try:
            self.query_one("#role-activity", RoleActivityPanel).update_roles(
                dashboard.roles,
                paused=dashboard.session.paused,
                skip_current=dashboard.session.skip_current,
            )
        except NoMatches:
            logger.debug("Error refreshing role activity", exc_info=True)

        try:
            self.query_one("#bootstrap-status", BootstrapStatusPanel).update_summary(dashboard.bootstrap)
        except NoMatches:
            logger.debug("Error refreshing bootstrap summary", exc_info=True)

        try:
            self.query_one("#graph-summary", ResearchGraphSummaryPanel).update_summary(dashboard.graph)
        except NoMatches:
            logger.debug("Error refreshing graph summary", exc_info=True)

        try:
            self.query_one("#frontier-focus", FrontierFocusPanel).update_frontiers(dashboard.frontiers)
        except NoMatches:
            logger.debug("Error refreshing frontier focus", exc_info=True)

        try:
            selected = self.selected_frontier_id
            if not selected or selected not in dashboard.frontier_details:
                selected = dashboard.frontiers[0].frontier_id if dashboard.frontiers else ""
                self.selected_frontier_id = selected
            if selected:
                self.query_one("#frontier-focus", FrontierFocusPanel).sync_selection(selected)
            self.query_one("#frontier-detail", FrontierDetailPanel).update_detail(
                dashboard.frontier_details.get(selected)
            )
        except NoMatches:
            logger.debug("Error refreshing frontier detail", exc_info=True)

        try:
            self.query_one("#lineage-timeline", LineageTimelinePanel).update_items(
                dashboard.lineage,
                dashboard.timeline,
            )
        except NoMatches:
            logger.debug("Error refreshing lineage timeline", exc_info=True)

        try:
            self.query_one("#execution-summary", ExecutionSummaryPanel).update_summary(
                dashboard.execution,
                phase_label=dashboard.session.phase_label,
            )
        except NoMatches:
            logger.debug("Error refreshing execution summary", exc_info=True)

        try:
            _active_dict = (
                {
                    "status": _active_role.status,
                    "detail": _active_role.detail,
                    "frontier_id": _active_role.frontier_id,
                    "execution_id": _active_role.execution_id,
                }
                if _active_role
                else None
            )
            self.query_one("#exp-status", ExperimentStatusPanel).update_status(
                _active_dict,
                completed=_completed,
                total=_total,
                phase=self.app_phase,
                role_label=_role_label,
            )
        except NoMatches:
            logger.debug("Error refreshing execution focus", exc_info=True)

        try:
            self.query_one("#recent-exp", RecentExperiments).update_results(
                dashboard.execution.recent_results,
                dashboard.execution.primary_metric,
            )
        except NoMatches:
            logger.debug("Error updating recent experiments", exc_info=True)

        try:
            self.query_one("#metric-chart", MetricChart).update_data(
                rows,
                dashboard.execution.primary_metric,
            )
        except NoMatches:
            logger.debug("Error updating metric chart", exc_info=True)

        try:
            self.query_one("#trace-banner", TraceBanner).update_trace(dashboard.trace_banner)
        except NoMatches:
            logger.debug("Error updating trace banner", exc_info=True)

        try:
            doc_viewer = self.query_one("#doc-viewer", DocViewer)
            docs_state = build_docs_workbench(
                self.research_dir,
                current_file=doc_viewer.current_file,
                doc_files=DocViewer.DOC_FILES,
                dynamic_files=DocViewer.DYNAMIC_FILES,
            )
            self.query_one("#docs-sidebar", DocsSidebarPanel).update_docs(
                docs_state.items,
                current_file=docs_state.current_file,
            )
        except NoMatches:
            logger.debug("Error updating docs sidebar", exc_info=True)

        try:
            active_tab = ""
            try:
                active_tab = self.query_one("#tabs", TabbedContent).active
            except NoMatches:
                pass
            self.query_one("#hotkey-bar", HotkeyBar).update_state(
                paused=dashboard.session.paused,
                phase=self.app_phase,
                active_tab=active_tab,
            )
        except NoMatches:
            logger.debug("Error updating hotkey bar", exc_info=True)

    def _read_control(self) -> dict:
        return read_control(self.research_dir / "control.json")

    def set_trace_banner(self, text: str) -> None:
        self.trace_banner_text = str(text or "").strip()

    def _write_control_command(
        self,
        command: Literal["pause", "resume", "skip_current", "clear_skip"],
        reason: str | None = None,
    ) -> bool:
        result = issue_control_command(
            self.research_dir / "control.json",
            command=command,
            source="tui",
            reason=reason,
        )
        applied = bool(result.get("applied", False))
        if not applied:
            logger.debug("Control command %s not applied: %s", command, result)
        return applied

    def action_pause(self) -> None:
        if self._dashboard_cache and self._dashboard_cache.session.paused:
            self.notify("Already paused", severity="warning")
            return
        self._write_control_command("pause", reason="paused from TUI hotkey")
        self.notify("Paused", severity="information")

    def action_resume(self) -> None:
        if self._dashboard_cache and not self._dashboard_cache.session.paused:
            self.notify("Already running", severity="warning")
            return
        self._write_control_command("resume")
        self.notify("Resumed", severity="information")

    def action_skip(self) -> None:
        if self.app_phase != "experimenting":
            self.notify("Skip only available during experimenting", severity="warning")
            return
        if self._dashboard_cache and self._dashboard_cache.session.skip_current:
            self.notify("Skip already queued", severity="warning")
            return
        self._write_control_command("skip_current")
        self.notify("Skip queued", severity="information")

    def action_clear_skip(self) -> None:
        if self.app_phase != "experimenting":
            self.notify("Skip only available during experimenting", severity="warning")
            return
        self._write_control_command("clear_skip")
        self.notify("Skip cancelled", severity="information")

    def action_gpu_status(self) -> None:
        gpu_path = self.research_dir / "gpu_status.json"
        gpus = []
        if gpu_path.exists():
            try:
                data = json.loads(gpu_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    gpus = data.get("gpus", [])
            except (json.JSONDecodeError, OSError, TypeError):
                pass
        self.push_screen(GPUStatusModal(gpus))

    def action_view_log(self) -> None:
        log_path = str(self.research_dir / "run.log")
        self.push_screen(LogScreen(log_path))

    async def action_next_doc(self) -> None:
        try:
            active_tab = self.query_one("#tabs", TabbedContent).active
            if active_tab != "tab-docs":
                return
            doc_viewer = self.query_one("#doc-viewer", DocViewer)
            idx = DocViewer.DOC_FILES.index(doc_viewer.current_file) if doc_viewer.current_file in DocViewer.DOC_FILES else -1
            next_idx = (idx + 1) % len(DocViewer.DOC_FILES)
            target = DocViewer.DOC_FILES[next_idx]
            await doc_viewer.select_doc(target)
            self.query_one("#docs-sidebar", DocsSidebarPanel).sync_selection(target)
        except (NoMatches, Exception):
            pass

    async def action_prev_doc(self) -> None:
        try:
            active_tab = self.query_one("#tabs", TabbedContent).active
            if active_tab != "tab-docs":
                return
            doc_viewer = self.query_one("#doc-viewer", DocViewer)
            idx = DocViewer.DOC_FILES.index(doc_viewer.current_file) if doc_viewer.current_file in DocViewer.DOC_FILES else 0
            prev_idx = (idx - 1) % len(DocViewer.DOC_FILES)
            target = DocViewer.DOC_FILES[prev_idx]
            await doc_viewer.select_doc(target)
            self.query_one("#docs-sidebar", DocsSidebarPanel).sync_selection(target)
        except (NoMatches, Exception):
            pass

    def action_quit_app(self) -> None:
        self.exit()

    def append_log(self, line: str) -> None:
        try:
            self.call_from_thread(self._do_append_log, line)
        except RuntimeError:
            pass

    def _do_append_log(self, line: str) -> None:
        try:
            self.query_one("#agent-log", RichLog).write(line)
        except NoMatches:
            pass

    append_idea_log = append_log
    append_exp_log = append_log
