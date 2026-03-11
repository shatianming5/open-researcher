"""Custom Textual widgets for the research-v1 command center."""

from __future__ import annotations

import json
import logging
import re

from rich.markup import escape
from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Collapsible, Input, OptionList, Static
from textual.widgets._option_list import Option

from open_researcher.tui.view_model import (
    BootstrapSummary,
    ClaimItem,
    DocNavItem,
    EvidenceItem,
    ExecutionSummary,
    FrontierCard,
    FrontierDetail,
    GraphSummary,
    LineageItem,
    RoleStatus,
    SessionChrome,
    TimelineItem,
)

logger = logging.getLogger(__name__)

C_SUCCESS = "#7dd4b0"
C_ERROR = "#ff7b72"
C_WARNING = "#f4bf75"
C_INFO = "#7dcfff"
C_PRIMARY = "#8bd5ff"
C_SECONDARY = "#a6da95"
C_ACCENT = "#c6a0f6"
C_TEXT = "#d7e1f3"
C_BEST = "#2ac3de"
C_DIM = "#6b7c93"
C_PANEL = "#101a26"
C_PANEL_ALT = "#0b141f"
C_SKY = "#5ac8fa"
C_CORAL = "#ff8f70"


def _format_metric(value) -> str:
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        text = str(value or "").strip()
        return text or "n/a"


def _chip(text: str, *, fg: str = C_TEXT, bg: str | None = None) -> str:
    label = escape(text.strip() or "n/a")
    if bg:
        return f"[bold {fg} on {bg}] {label} [/]"
    return f"[bold {fg}]{label}[/]"


def _status_color(status: str) -> str:
    value = str(status or "").strip()
    return {
        "running": C_INFO,
        "approved": C_SUCCESS,
        "completed": C_SUCCESS,
        "resolved": C_SUCCESS,
        "cached": C_SUCCESS,
        "pending": C_DIM,
        "disabled": C_DIM,
        "skipped": C_DIM,
        "draft": C_WARNING,
        "needs_post_review": C_WARNING,
        "needs_repro": C_WARNING,
        "unresolved": C_WARNING,
        "promoted": C_SUCCESS,
        "under_review": C_INFO,
        "discard": C_WARNING,
        "discarded": C_WARNING,
        "crash": C_ERROR,
        "failed": C_ERROR,
        "rejected": C_ERROR,
        "downgraded": C_WARNING,
    }.get(value, C_DIM)


def _role_label(status: str) -> str:
    value = str(status or "").strip() or "idle"
    return value.replace("_", " ").upper()


def _metric_delta_text(value: float | None, reference: float | None, *, direction: str, label: str) -> str:
    if value is None or reference is None:
        return f"[{C_DIM}]{escape(label)}[/] [dim]n/a[/]"
    delta = value - reference
    improved = delta < 0 if direction == "lower_is_better" else delta > 0
    if abs(delta) < 1e-12:
        color = C_DIM
        verdict = "flat"
    else:
        color = C_SUCCESS if improved else C_CORAL
        verdict = "better" if improved else "worse"
    return f"[{C_DIM}]{escape(label)}[/] [{color}]{delta:+.4f} ({verdict})[/]"


def _highlight_match(text: str, query: str, *, color: str = C_WARNING) -> str:
    raw = str(text or "")
    needle = str(query or "").strip()
    if not raw:
        return ""
    if not needle:
        return escape(raw)
    pattern = re.compile(re.escape(needle), re.IGNORECASE)
    parts: list[str] = []
    cursor = 0
    for match in pattern.finditer(raw):
        start, end = match.span()
        if start > cursor:
            parts.append(escape(raw[cursor:start]))
        parts.append(f"[bold {color}]{escape(raw[start:end])}[/]")
        cursor = end
    if cursor < len(raw):
        parts.append(escape(raw[cursor:]))
    return "".join(parts)


class StatsBar(Static):
    """Global command center header."""

    stats_text = reactive("")

    def render(self) -> str:
        return self.stats_text or "[bold]Open Researcher[/bold] [dim]booting command center...[/dim]"

    def update_stats(self, state: dict, phase: str = "", paused: bool = False) -> None:
        total = int(state.get("total", 0) or 0)
        keep = int(state.get("keep", 0) or 0)
        discard = int(state.get("discard", 0) or 0)
        crash = int(state.get("crash", 0) or 0)
        best = state.get("best_value")
        protocol = str(state.get("protocol", "") or "research-v1")
        branch = str(state.get("branch", "") or "unknown")
        graph = state.get("graph") if isinstance(state.get("graph"), dict) else {}
        runnable = int(graph.get("frontier_runnable", 0) or 0)

        phase_badges = {
            "scouting": _chip("Scout", fg="#08111a", bg=C_PRIMARY),
            "preparing": _chip("Prepare", fg="#08111a", bg=C_WARNING),
            "reviewing": _chip("Review", fg="#08111a", bg=C_WARNING),
            "experimenting": _chip("Research", fg="#08111a", bg=C_SUCCESS),
        }

        parts: list[str] = []
        if phase in phase_badges:
            parts.append(phase_badges[phase])
        parts.append(f"[bold {C_TEXT}]OPEN RESEARCHER[/]")
        parts.append(f"[{C_INFO}]{escape(protocol)}[/]")
        parts.append(f"[{C_DIM}]branch {escape(branch)}[/]")
        if paused:
            parts.append(_chip("PAUSED", fg="#08111a", bg=C_CORAL))
        parts.append(f"[{C_SUCCESS}]{keep}K[/] [{C_WARNING}]{discard}D[/] [{C_ERROR}]{crash}C[/]")
        if runnable:
            parts.append(f"[{C_PRIMARY}]frontier {runnable}[/]")
        if total == 0:
            parts.append(f"[{C_DIM}]waiting for first experiment[/]")
        elif best is not None:
            parts.append(f"[bold {C_BEST}]best={_format_metric(best)}[/]")
        self.stats_text = "  ".join(parts)


class SessionChromeBar(Static):
    """Session summary panel shown on the command page."""

    chrome_text = reactive("", layout=True)

    def render(self) -> str:
        return self.chrome_text or "[dim]No session state yet[/dim]"

    def update_chrome(self, chrome: SessionChrome) -> None:
        mode_label = chrome.mode.replace("_", " ")
        phase_line = _chip(chrome.phase_label or chrome.phase or "idle", fg="#08111a", bg=C_PRIMARY)
        control_bits = []
        if chrome.paused:
            control_bits.append(_chip("Paused", fg="#08111a", bg=C_CORAL))
        if chrome.skip_current:
            control_bits.append(_chip("Skip queued", fg="#08111a", bg=C_WARNING))
        control_suffix = " ".join(control_bits) if control_bits else f"[{C_DIM}]runtime live[/]"
        metric_name = escape(chrome.primary_metric or "metric")
        config_line = f"[{C_DIM}]protocol[/] [{C_PRIMARY}]{escape(chrome.protocol)}[/]  [{C_DIM}]mode[/] [{C_TEXT}]{escape(mode_label)}[/]  [{C_DIM}]branch[/] [{C_TEXT}]{escape(chrome.branch)}[/]"
        metric_line = (
            f"[{C_DIM}]metric[/] [bold {C_TEXT}]{metric_name}[/]  "
            f"[{C_DIM}]baseline[/] [{C_INFO}]{_format_metric(chrome.baseline_value)}[/]  "
            f"[{C_DIM}]current[/] [{C_SECONDARY}]{_format_metric(chrome.current_value)}[/]  "
            f"[{C_DIM}]best[/] [bold {C_BEST}]{_format_metric(chrome.best_value)}[/]"
        )
        volume_line = (
            f"[{C_DIM}]results[/] [{C_TEXT}]{chrome.total}[/]  "
            f"[{C_SUCCESS}]keep {chrome.keep}[/]  "
            f"[{C_WARNING}]discard {chrome.discard}[/]  "
            f"[{C_ERROR}]crash {chrome.crash}[/]  "
            f"[{C_PRIMARY}]runnable {chrome.frontier_runnable}[/]"
        )
        lines = [
            f"[bold {C_TEXT}]Research Command Center[/]  {phase_line}  {control_suffix}",
            config_line,
            metric_line,
            volume_line,
        ]
        if chrome.config_error:
            lines.append(f"[{C_CORAL}]Config:[/] {escape(chrome.config_error)}")
        if chrome.graph_error:
            lines.append(f"[{C_CORAL}]Graph:[/] {escape(chrome.graph_error)}")
        self.chrome_text = "\n".join(lines)


class BootstrapStatusPanel(Static):
    """Repository prepare/bootstrap status."""

    summary_text = reactive("", layout=True)

    def render(self) -> str:
        return self.summary_text or "[dim]Bootstrap state unavailable[/dim]"

    def update_summary(self, summary: BootstrapSummary) -> None:
        status_chip = _chip(summary.status.replace("_", " "), fg="#08111a", bg=_status_color(summary.status))
        step_line = (
            f"[{C_DIM}]install[/] {_chip(summary.install_status, fg='#08111a', bg=_status_color(summary.install_status))}  "
            f"[{C_DIM}]data[/] {_chip(summary.data_status, fg='#08111a', bg=_status_color(summary.data_status))}  "
            f"[{C_DIM}]smoke[/] {_chip(summary.smoke_status, fg='#08111a', bg=_status_color(summary.smoke_status))}"
        )
        lines = [
            f"[bold {C_TEXT}]Repository Prepare[/]  {status_chip}",
            f"[{C_DIM}]working dir[/] [{C_TEXT}]{escape(summary.working_dir)}[/]  "
            f"[{C_DIM}]python[/] [{C_INFO}]{escape(summary.python_executable or 'unresolved')}[/]",
            step_line,
        ]
        if summary.missing_paths:
            lines.append(f"[{C_WARNING}]missing paths:[/] {escape(', '.join(summary.missing_paths))}")
        if summary.unresolved:
            for item in summary.unresolved:
                lines.append(f"[{C_WARNING}]unresolved:[/] {escape(item)}")
        if summary.errors:
            for item in summary.errors:
                lines.append(f"[{C_CORAL}]error:[/] {escape(item)}")
        if summary.log_path:
            lines.append(f"[{C_DIM}]log[/] {escape(summary.log_path)}")
        self.summary_text = "\n".join(lines)


class RoleActivityPanel(Static):
    """Render manager / critic / experiment live role states."""

    roles_text = reactive("", layout=True)

    def render(self) -> str:
        return self.roles_text or "[dim]No role activity yet[/dim]"

    def update_roles(self, roles: list[RoleStatus], *, paused: bool = False, skip_current: bool = False) -> None:
        if not roles:
            self.roles_text = "[dim]No role activity yet[/dim]"
            return

        header_bits = [f"[bold {C_TEXT}]Role Activity[/]"]
        if paused:
            header_bits.append(_chip("Paused", fg="#08111a", bg=C_CORAL))
        if skip_current:
            header_bits.append(_chip("Skip", fg="#08111a", bg=C_WARNING))
        lines = ["  ".join(header_bits)]

        for role in roles:
            color = _status_color(role.status)
            status_chip = _chip(_role_label(role.status), fg="#08111a", bg=color)
            meta = []
            if role.frontier_id:
                meta.append(f"[{C_PRIMARY}]{escape(role.frontier_id)}[/]")
            if role.execution_id:
                meta.append(f"[{C_DIM}]{escape(role.execution_id)}[/]")
            if role.worker_count:
                meta.append(f"[{C_INFO}]{role.worker_count} worker(s)[/]")
            detail = escape(role.detail or "idle")
            lines.append(f"[bold {C_TEXT}]{escape(role.label)}[/]  {status_chip}")
            if meta:
                lines.append(f"[{C_DIM}]{'  '.join(meta)}[/]")
            lines.append(f"[{C_DIM}]{detail}[/]")
            lines.append("")

        self.roles_text = "\n".join(lines).rstrip()


class ResearchGraphSummaryPanel(Static):
    """Research graph and memory summary."""

    summary_text = reactive("", layout=True)

    def render(self) -> str:
        return self.summary_text or "[dim]No research graph yet[/dim]"

    def update_summary(self, summary: GraphSummary) -> None:
        counts = summary.frontier_status_counts
        frontier_bits = [
            f"[{C_PRIMARY}]runnable {summary.frontier_runnable}[/]",
            f"[{C_WARNING}]draft {counts.get('draft', 0)}[/]",
            f"[{C_INFO}]running {counts.get('running', 0)}[/]",
            f"[{C_WARNING}]post {counts.get('needs_post_review', 0)}[/]",
            f"[{C_WARNING}]repro {counts.get('needs_repro', 0)}[/]",
        ]
        lines = [
            f"[bold {C_TEXT}]Research Graph[/]",
            f"[{C_DIM}]hypotheses[/] [{C_TEXT}]{summary.hypotheses}[/]  [{C_DIM}]specs[/] [{C_TEXT}]{summary.experiment_specs}[/]  [{C_DIM}]evidence[/] [{C_TEXT}]{summary.evidence}[/]  [{C_DIM}]claims[/] [{C_TEXT}]{summary.claims}[/]",
            f"[{C_DIM}]frontier[/] [{C_TEXT}]{summary.frontier_total}[/]  " + "  ".join(frontier_bits),
            f"[{C_DIM}]memory[/] priors {summary.repo_type_priors}  ideation {summary.ideation_memory}  experiment {summary.experiment_memory}",
        ]
        self.summary_text = "\n".join(lines)


class ProjectedBacklogPanel(Static):
    """Research frontier focus cards."""

    items_text = reactive("", layout=True)

    def render(self) -> str:
        return ""

    class FrontierRequested(Message):
        """Request emitted when the operator selects a frontier card."""

        def __init__(self, panel: "ProjectedBacklogPanel", frontier_id: str) -> None:
            super().__init__()
            self.panel = panel
            self.frontier_id = frontier_id

    DEFAULT_CSS = """
    ProjectedBacklogPanel {
        height: 1fr;
    }
    ProjectedBacklogPanel #frontier-options {
        height: 1fr;
    }
    ProjectedBacklogPanel #frontier-active {
        height: auto;
        margin-top: 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._frontier_map: dict[str, FrontierCard] = {}

    def compose(self) -> ComposeResult:
        yield Static("", id="frontier-header")
        yield OptionList(id="frontier-options", markup=True)
        yield Static("", id="frontier-active")

    def update_frontiers(self, frontiers: list[FrontierCard]) -> None:
        if not frontiers:
            self.items_text = "[dim]No projected backlog items yet[/dim]"
            try:
                self.query_one("#frontier-header", Static).update("[dim]No projected backlog items yet[/dim]")
                self.query_one("#frontier-options", OptionList).set_options([])
                self.query_one("#frontier-active", Static).update("")
            except Exception:
                logger.debug("Error updating empty frontier panel", exc_info=True)
            return

        self._frontier_map = {item.frontier_id: item for item in frontiers}
        lines = [f"[bold {C_TEXT}]Frontier Focus[/]"]
        options: list[Option] = []
        for item in frontiers:
            status_chip = _chip(item.status.replace("_", " "), fg="#08111a", bg=_status_color(item.status))
            priority_chip = _chip(f"P{item.priority}", fg="#08111a", bg=C_ACCENT)
            repro_chip = f" {_chip('REPRO', fg='#08111a', bg=C_WARNING)}" if item.repro_required else ""
            trace_bits = [escape(item.frontier_id)]
            if item.execution_id:
                trace_bits.append(escape(item.execution_id))
            trace_bits.append(escape(item.reason_code))
            lines.append(f"{priority_chip} {status_chip}{repro_chip}")
            lines.append(f"[bold {C_PRIMARY}]{' / '.join(trace_bits)}[/]")
            if item.hypothesis_summary:
                lines.append(f"[{C_TEXT}]H:[/] {escape(item.hypothesis_summary)}")
            if item.spec_summary:
                lines.append(f"[{C_TEXT}]S:[/] {escape(item.spec_summary)}")
            if item.attribution_focus:
                lines.append(f"[{C_DIM}]Focus:[/] {escape(item.attribution_focus)}")
            if item.expected_signal:
                lines.append(f"[{C_DIM}]Signal:[/] {escape(item.expected_signal)}")
            tail = [f"[{C_DIM}]claim[/] {escape(item.claim_state)}", f"[{C_DIM}]risk[/] {escape(item.risk_level)}"]
            if item.metric_value:
                tail.append(f"[{C_DIM}]metric[/] {_format_metric(item.metric_value)}")
            lines.append("  ".join(tail))
            lines.append("")
            label = (
                f"[{C_PRIMARY}]P{item.priority}[/] "
                f"[{_status_color(item.status)}]{escape(item.frontier_id)}[/] "
                f"[{C_DIM}]{escape(item.spec_summary or item.hypothesis_summary)}[/]"
            )
            options.append(Option(label, id=item.frontier_id))

        self.items_text = "\n".join(lines).rstrip()
        try:
            self.query_one("#frontier-header", Static).update(
                f"[bold {C_TEXT}]Frontier Focus[/]\n[{C_DIM}]Select a frontier to inspect hypothesis, spec, and evidence[/]"
            )
            option_list = self.query_one("#frontier-options", OptionList)
            option_list.set_options(options)
            option_list.highlighted = 0 if options else None
            self._update_active(frontiers[0].frontier_id)
        except Exception:
            logger.debug("Error updating frontier panel", exc_info=True)

    def update_items(self, ideas: list[dict]) -> None:
        cards: list[FrontierCard] = []
        for idea in ideas:
            if not isinstance(idea, dict):
                continue
            reason_code = str(idea.get("review_reason_code", "")).strip()
            if not reason_code or reason_code == "unspecified":
                reason_code = str(idea.get("selection_reason_code", "")).strip() or "manager_refresh"
            metric_value = ""
            result = idea.get("result")
            if isinstance(result, dict) and result.get("metric_value") not in ("", None):
                metric_value = str(result.get("metric_value"))
            cards.append(
                FrontierCard(
                    frontier_id=str(idea.get("frontier_id", "")).strip() or str(idea.get("id", "")).strip(),
                    execution_id=str(idea.get("execution_id", "")).strip(),
                    idea_id=str(idea.get("id", "")).strip(),
                    priority=int(idea.get("priority", 5) or 5),
                    status=str(idea.get("status", "pending") or "pending").strip(),
                    claim_state=str(idea.get("claim_state", "candidate") or "candidate").strip(),
                    repro_required=bool(idea.get("repro_required", False)),
                    hypothesis_summary=str(idea.get("hypothesis_summary", "")).strip(),
                    spec_summary=str(idea.get("spec_summary", "") or idea.get("description", "")).strip(),
                    description=str(idea.get("description", "")).strip(),
                    attribution_focus=str(idea.get("attribution_focus", "")).strip(),
                    expected_signal=str(idea.get("expected_signal", "")).strip(),
                    risk_level=str(idea.get("risk_level", "")).strip() or "medium",
                    reason_code=reason_code,
                    metric_value=metric_value,
                )
            )
        cards.sort(key=lambda item: (item.priority, item.frontier_id))
        self.update_frontiers(cards)

    def update_ideas(self, ideas: list[dict]) -> None:
        self.update_items(ideas)


class FrontierFocusPanel(ProjectedBacklogPanel):
    """Explicit name for the projected frontier panel."""

    def sync_selection(self, frontier_id: str) -> None:
        if not frontier_id:
            return
        try:
            option_list = self.query_one("#frontier-options", OptionList)
        except Exception:
            return
        for index, option in enumerate(option_list.options):
            if option.id == frontier_id:
                option_list.highlighted = index
                self._update_active(frontier_id)
                return

    def _update_active(self, frontier_id: str) -> None:
        item = self._frontier_map.get(frontier_id)
        if item is None:
            return
        chips = [
            _chip(item.status.replace("_", " "), fg="#08111a", bg=_status_color(item.status)),
            _chip(f"P{item.priority}", fg="#08111a", bg=C_ACCENT),
        ]
        if item.repro_required:
            chips.append(_chip("REPRO", fg="#08111a", bg=C_WARNING))
        preview = [
            f"[bold {C_TEXT}]Active Frontier[/]  {' '.join(chips)}",
            f"[{C_PRIMARY}]{escape(item.frontier_id)}[/]  [{C_DIM}]{escape(item.execution_id)}[/]  [{C_DIM}]{escape(item.reason_code)}[/]",
            f"[{C_TEXT}]{escape(item.hypothesis_summary or item.spec_summary or item.description)}[/]",
        ]
        self.query_one("#frontier-active", Static).update("\n".join(preview))

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_id:
            self._update_active(event.option_id)
            self.post_message(self.FrontierRequested(self, event.option_id))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_id:
            self._update_active(event.option_id)
            self.post_message(self.FrontierRequested(self, event.option_id))


class FrontierDetailPanel(Static):
    """Full detail drawer for the selected frontier."""

    body_text = reactive("", layout=True)

    DEFAULT_CSS = """
    FrontierDetailPanel {
        height: 1fr;
    }
    FrontierDetailPanel #frontier-detail-summary {
        height: auto;
        margin-bottom: 1;
    }
    FrontierDetailPanel Collapsible {
        margin-top: 1;
        height: auto;
    }
    FrontierDetailPanel .detail-block {
        height: auto;
        padding: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="frontier-detail-summary")
        with Collapsible(title="Hypothesis", collapsed=False, id="frontier-detail-hypothesis-box"):
            yield Static("", id="frontier-detail-hypothesis", classes="detail-block")
        with Collapsible(title="Experiment Spec", collapsed=False, id="frontier-detail-spec-box"):
            yield Static("", id="frontier-detail-spec", classes="detail-block")
        with Collapsible(title="Metric & Evidence", collapsed=False, id="frontier-detail-evidence-box"):
            yield Static("", id="frontier-detail-evidence", classes="detail-block")
        with Collapsible(title="Claims", collapsed=False, id="frontier-detail-claims-box"):
            yield Static("", id="frontier-detail-claims", classes="detail-block")

    def render(self) -> str:
        return ""

    def _set_block(self, selector: str, text: str) -> None:
        try:
            self.query_one(selector, Static).update(text)
        except Exception:
            logger.debug("Error updating detail block %s", selector, exc_info=True)

    def _set_title(self, selector: str, title: str) -> None:
        try:
            self.query_one(selector, Collapsible).title = title
        except Exception:
            logger.debug("Error updating detail section title %s", selector, exc_info=True)

    def update_detail(self, detail: FrontierDetail | None) -> None:
        if detail is None:
            self.body_text = "[dim]Select a frontier to inspect hypothesis, spec, evidence, and claims[/dim]"
            self._set_block("#frontier-detail-summary", self.body_text)
            self._set_block("#frontier-detail-hypothesis", self.body_text)
            self._set_block("#frontier-detail-spec", self.body_text)
            self._set_block("#frontier-detail-evidence", self.body_text)
            self._set_block("#frontier-detail-claims", self.body_text)
            return

        frontier = detail.frontier
        chips = [
            _chip(frontier.status.replace("_", " "), fg="#08111a", bg=_status_color(frontier.status)),
            _chip(f"P{frontier.priority}", fg="#08111a", bg=C_ACCENT),
            _chip(frontier.claim_state, fg="#08111a", bg=C_INFO),
        ]
        if frontier.repro_required:
            chips.append(_chip("REPRO", fg="#08111a", bg=C_WARNING))

        summary_lines = [
            f"[bold {C_TEXT}]Frontier Detail[/]  {' '.join(chips)}",
            f"[{C_PRIMARY}]{escape(frontier.frontier_id)}[/]  [{C_DIM}]{escape(frontier.execution_id)}[/]  [{C_DIM}]{escape(frontier.reason_code)}[/]",
            f"[{C_DIM}]metric[/] [{C_TEXT}]{escape(detail.primary_metric or 'metric')}[/]  "
            f"[{C_DIM}]latest[/] [{C_INFO}]{_format_metric(detail.latest_metric_value)}[/]  "
            f"[{C_DIM}]best observed[/] [bold {C_BEST}]{_format_metric(detail.best_metric_value)}[/]  "
            f"[{C_DIM}]samples[/] [{C_TEXT}]{detail.metric_samples}[/]",
        ]
        if detail.metric_samples:
            summary_lines.append(
                "  ".join(
                    [
                        _metric_delta_text(
                            detail.latest_metric_value,
                            detail.baseline_value,
                            direction=detail.direction,
                            label="vs baseline",
                        ),
                        _metric_delta_text(
                            detail.latest_metric_value,
                            detail.current_value,
                            direction=detail.direction,
                            label="vs current",
                        ),
                        _metric_delta_text(
                            detail.best_metric_value,
                            detail.global_best_value,
                            direction=detail.direction,
                            label="best vs global",
                        ),
                    ]
                )
            )
        elif frontier.metric_value:
            summary_lines.append(
                f"[{C_DIM}]projected metric[/] [{C_INFO}]{_format_metric(frontier.metric_value)}[/]"
            )

        hypothesis_lines = [
            f"[bold {C_TEXT}]{escape(frontier.hypothesis_summary or detail.hypothesis_id or frontier.description)}[/]",
        ]
        if detail.hypothesis_rationale:
            hypothesis_lines.append(f"[{C_DIM}]Rationale:[/] {escape(detail.hypothesis_rationale)}")
        if detail.expected_evidence:
            hypothesis_lines.append(
                f"[{C_DIM}]Expected evidence:[/] {escape(', '.join(detail.expected_evidence))}"
            )

        spec_lines = [
            f"[bold {C_TEXT}]{escape(frontier.spec_summary or detail.experiment_spec_id or frontier.description)}[/]",
        ]
        if detail.change_plan:
            spec_lines.append(f"[{C_DIM}]Change:[/] {escape(detail.change_plan)}")
        if detail.evaluation_plan:
            spec_lines.append(f"[{C_DIM}]Evaluation:[/] {escape(detail.evaluation_plan)}")
        if frontier.attribution_focus:
            spec_lines.append(f"[{C_DIM}]Attribution:[/] {escape(frontier.attribution_focus)}")
        if frontier.expected_signal:
            spec_lines.append(f"[{C_DIM}]Signal:[/] {escape(frontier.expected_signal)}")

        evidence_lines = []
        if detail.evidence_reliability_counts:
            reliability_parts = []
            for key, count in sorted(detail.evidence_reliability_counts.items()):
                reliability_parts.append(
                    f"[{_status_color(key)}]{escape(key)}[/] [{C_TEXT}]{count}[/]"
                )
            evidence_lines.append("  ".join(reliability_parts))
        evidence_lines.append(
            f"[{C_DIM}]baseline[/] [{C_INFO}]{_format_metric(detail.baseline_value)}[/]  "
            f"[{C_DIM}]current[/] [{C_SECONDARY}]{_format_metric(detail.current_value)}[/]  "
            f"[{C_DIM}]global best[/] [bold {C_BEST}]{_format_metric(detail.global_best_value)}[/]"
        )
        if detail.evidence:
            for item in detail.evidence[:4]:
                trace = " / ".join(part for part in [item.evidence_id, item.execution_id, item.reason_code] if part)
                metric = f"  [{C_INFO}]{_format_metric(item.metric_value)}[/]" if item.metric_value else ""
                evidence_lines.append(f"[{_status_color(item.reliability)}]{escape(trace)}[/]{metric}")
                evidence_lines.append(f"[{C_TEXT}]{escape(item.description)}[/]")
        else:
            evidence_lines.append(f"[{C_DIM}]No evidence recorded for this frontier yet[/]")

        claim_lines = []
        if detail.claims:
            for item in detail.claims[:4]:
                trace = " / ".join(part for part in [item.claim_update_id, item.execution_id, item.reason_code] if part)
                claim_lines.append(f"[{_status_color(item.transition)}]{escape(trace)}[/]")
                claim_lines.append(
                    f"[{C_TEXT}]{escape(item.transition)}[/]  [{C_DIM}]confidence[/] {escape(item.confidence)}"
                )
        else:
            claim_lines.append(f"[{C_DIM}]No claim updates recorded for this frontier yet[/]")

        self.body_text = "\n".join(
            summary_lines
            + [""]
            + hypothesis_lines
            + [""]
            + spec_lines
            + [""]
            + evidence_lines
            + [""]
            + claim_lines
        )

        self._set_title(
            "#frontier-detail-hypothesis-box",
            f"Hypothesis · {frontier.frontier_id}",
        )
        self._set_title(
            "#frontier-detail-spec-box",
            f"Experiment Spec · {detail.experiment_spec_id or frontier.execution_id or 'selected'}",
        )
        self._set_title(
            "#frontier-detail-evidence-box",
            f"Metric & Evidence · {detail.metric_samples} sample(s)",
        )
        self._set_title(
            "#frontier-detail-claims-box",
            f"Claims · {len(detail.claims)} update(s)",
        )
        self._set_block("#frontier-detail-summary", "\n".join(summary_lines))
        self._set_block("#frontier-detail-hypothesis", "\n".join(hypothesis_lines))
        self._set_block("#frontier-detail-spec", "\n".join(spec_lines))
        self._set_block("#frontier-detail-evidence", "\n".join(evidence_lines))
        self._set_block("#frontier-detail-claims", "\n".join(claim_lines))


class IdeaListPanel(ProjectedBacklogPanel):
    """Backward-compatible alias for tests/imports."""

    def update_ideas(self, ideas: list[dict]) -> None:
        if not ideas:
            self.items_text = "[dim]No projected backlog items yet[/dim]"
            return

        def _sort_key(idea: dict) -> tuple[int, str]:
            return (int(idea.get("priority", 9999) or 9999), str(idea.get("id", "")))

        lines: list[str] = []
        for idea in sorted(ideas, key=_sort_key):
            status = str(idea.get("status", "pending")).strip() or "pending"
            result = idea.get("result")
            verdict = result.get("verdict", "") if isinstance(result, dict) else ""
            if status == "running":
                icon = "▶"
                result_str = "running..."
            elif verdict == "kept" or (status == "done" and verdict != "discarded"):
                icon = "✓"
                metric = result.get("metric_value") if isinstance(result, dict) else None
                suffix = f" val={_format_metric(metric)}" if metric not in ("", None) else ""
                result_str = f"kept{suffix}"
            elif verdict == "discarded":
                icon = "✗"
                metric = result.get("metric_value") if isinstance(result, dict) else None
                suffix = f" val={_format_metric(metric)}" if metric not in ("", None) else ""
                result_str = f"disc{suffix}"
            elif status == "pending":
                icon = "·"
                result_str = "pending"
            elif status == "skipped":
                icon = "–"
                result_str = "skipped"
            else:
                icon = "?"
                result_str = status

            desc = str(idea.get("description", "")).strip()
            if len(desc) > 50:
                desc = desc[:47] + "..."
            item_label = str(idea.get("frontier_id", "")).strip() or str(idea.get("id", "item")).strip()
            lines.append(f"  {icon} {item_label} | {desc}  -> {result_str}")

        self.items_text = "\n".join(lines)

    @property
    def ideas_text(self) -> str:
        return self.items_text


class EvidenceClaimsPanel(Static):
    """Show recent evidence and claim lineage."""

    body_text = reactive("", layout=True)

    def render(self) -> str:
        return self.body_text or "[dim]No evidence or claim updates yet[/dim]"

    def update_items(self, evidence: list[EvidenceItem], claims: list[ClaimItem]) -> None:
        lines = [f"[bold {C_TEXT}]Evidence & Claims[/]"]
        if not evidence and not claims:
            lines.append(f"[{C_DIM}]No evidence or claim updates yet[/]")
            self.body_text = "\n".join(lines)
            return

        if evidence:
            lines.append(f"[{C_PRIMARY}]Recent Evidence[/]")
            for item in evidence[:4]:
                trace = " / ".join(
                    part for part in [item.evidence_id, item.frontier_id, item.execution_id] if part
                )
                lines.append(
                    f"[{_status_color(item.reliability)}]{escape(trace)}[/]  "
                    f"[{C_DIM}]{escape(item.reason_code)}[/]"
                )
                detail = escape(item.description)
                if item.metric_value:
                    detail += f"  [{C_INFO}]{_format_metric(item.metric_value)}[/]"
                lines.append(detail)
            lines.append("")

        if claims:
            lines.append(f"[{C_ACCENT}]Recent Claims[/]")
            for item in claims[:4]:
                trace = " / ".join(
                    part for part in [item.claim_update_id, item.frontier_id, item.execution_id] if part
                )
                lines.append(
                    f"[{_status_color(item.transition)}]{escape(trace)}[/]  "
                    f"[{C_DIM}]{escape(item.reason_code)}[/]"
                )
                lines.append(
                    f"[{C_TEXT}]{escape(item.transition)}[/]  "
                    f"[{C_DIM}]confidence[/] {escape(item.confidence)}"
                )

        self.body_text = "\n".join(lines).rstrip()


class LineageTimelinePanel(Static):
    """Show branch lineage and recent runtime timeline."""

    body_text = reactive("", layout=True)

    def render(self) -> str:
        return self.body_text or "[dim]No lineage or timeline data yet[/dim]"

    def update_items(self, lineage: list[LineageItem], timeline: list[TimelineItem]) -> None:
        lines = [f"[bold {C_TEXT}]Lineage & Timeline[/]"]
        if lineage:
            lines.append(f"[{C_ACCENT}]Hypothesis Tree[/]")
            lines.extend(self._render_tree(lineage))
            lines.append("")
        if timeline:
            lines.append(f"[{C_SKY}]Recent Timeline[/]")
            for item in timeline[:5]:
                stamp = item.ts[11:19] if len(item.ts) >= 19 else item.ts or "--:--:--"
                trace = " / ".join(part for part in [item.frontier_id, item.execution_id, item.reason_code] if part)
                detail = escape(item.detail or item.event.replace("_", " "))
                lines.append(f"[{C_DIM}]{escape(stamp)}[/] [{C_INFO}]{escape(item.event)}[/] [{C_TEXT}]{detail}[/]")
                if trace:
                    lines.append(f"[{C_DIM}]{escape(trace)}[/]")
        if len(lines) == 1:
            lines.append(f"[{C_DIM}]No lineage or timeline data yet[/]")
        self.body_text = "\n".join(lines).rstrip()

    def _render_tree(self, lineage: list[LineageItem]) -> list[str]:
        if not lineage:
            return [f"[{C_DIM}]No branch relations yet[/]"]

        children: dict[str, list[LineageItem]] = {}
        parent_summaries: dict[str, str] = {}
        child_summaries: dict[str, str] = {}
        parent_ids: set[str] = set()
        child_ids: set[str] = set()
        for item in lineage:
            parent = item.parent_id or "root"
            child = item.child_id or "child"
            children.setdefault(parent, []).append(item)
            parent_ids.add(parent)
            child_ids.add(child)
            if item.parent_summary:
                parent_summaries[parent] = item.parent_summary
            if item.child_summary:
                child_summaries[child] = item.child_summary

        roots = [parent for parent in parent_ids if parent not in child_ids]
        if not roots and lineage:
            roots = [lineage[0].parent_id or "root"]

        def _node_text(node_id: str) -> str:
            summary = child_summaries.get(node_id) or parent_summaries.get(node_id) or node_id
            return f"[{C_PRIMARY}]{escape(node_id)}[/] [{C_DIM}]·[/] [{C_TEXT}]{escape(summary)}[/]"

        lines: list[str] = []
        visited: set[str] = set()

        def _walk(node_id: str, prefix: str = "") -> None:
            if node_id in visited:
                lines.append(f"{prefix}[{C_WARNING}]↺[/] {_node_text(node_id)}")
                return
            visited.add(node_id)
            lines.append(f"{prefix}[{C_SECONDARY}]●[/] {_node_text(node_id)}")
            branch_items = children.get(node_id, [])
            for index, item in enumerate(branch_items):
                connector = "└─" if index == len(branch_items) - 1 else "├─"
                child_prefix = f"{prefix}{'   ' if index == len(branch_items) - 1 else '│  '}"
                lines.append(
                    f"{prefix}[{C_ACCENT}]{connector} {escape(item.relation)}[/] "
                    f"[{C_PRIMARY}]{escape(item.child_id or 'child')}[/]"
                )
                _walk(item.child_id or "child", child_prefix)

        for root in roots[:3]:
            _walk(root)
        if len(roots) > 3:
            lines.append(f"[{C_DIM}]… {len(roots) - 3} more root branch(es)[/]")
        return lines


class DocsSidebarPanel(Static):
    """Sidebar navigator with doc availability and short previews."""

    body_text = reactive("", layout=True)

    class DocRequested(Message):
        """Request emitted when the operator selects a document from the sidebar."""

        def __init__(self, panel: "DocsSidebarPanel", filename: str) -> None:
            super().__init__()
            self.panel = panel
            self.filename = filename

    DEFAULT_CSS = """
    DocsSidebarPanel {
        height: 1fr;
    }
    DocsSidebarPanel #docs-search {
        margin-top: 1;
    }
    DocsSidebarPanel #docs-recent {
        height: auto;
        margin-top: 1;
    }
    DocsSidebarPanel #docs-options {
        height: 1fr;
        margin-top: 1;
    }
    DocsSidebarPanel #docs-preview {
        height: auto;
        margin-top: 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._doc_index: dict[str, DocNavItem] = {}
        self._all_items: list[DocNavItem] = []
        self._recent_files: list[str] = []
        self._query: str = ""
        self._current_file: str = ""

    def compose(self) -> ComposeResult:
        yield Static("", id="docs-sidebar-header")
        yield Input(placeholder="Search docs...", id="docs-search")
        yield Static("", id="docs-recent")
        yield OptionList(id="docs-options", markup=True)
        yield Static("", id="docs-preview")

    def render(self) -> str:
        return ""

    def update_docs(self, items: list[DocNavItem], *, current_file: str) -> None:
        if not items:
            self.body_text = "[dim]No document index yet[/dim]"
            try:
                self.query_one("#docs-sidebar-header", Static).update("[dim]No document index yet[/dim]")
                self.query_one("#docs-recent", Static).update("")
                self.query_one("#docs-options", OptionList).set_options([])
                self.query_one("#docs-preview", Static).update("")
            except Exception:
                logger.debug("Error updating empty docs sidebar", exc_info=True)
            return
        self._all_items = list(items)
        self._doc_index = {item.filename: item for item in items}
        self._current_file = current_file
        self._remember_recent(current_file)
        header_text = f"[bold {C_TEXT}]Docs Navigator[/]\n[{C_DIM}]Click or press Enter to open a document[/]"
        lines = [f"[bold {C_TEXT}]Docs Navigator[/]"]
        for item in items:
            active = item.filename == current_file
            bullet = "▸" if active else "•"
            color = C_PRIMARY if active else (C_SECONDARY if item.available else C_DIM)
            active_chip = f" {_chip('LIVE', fg='#08111a', bg=C_PRIMARY)}" if active else ""
            dynamic_chip = f" {_chip('GEN', fg='#08111a', bg=C_WARNING)}" if item.dynamic else ""
            lines.append(f"[{color}]{bullet} {escape(item.title)}[/]{active_chip}{dynamic_chip}")
            lines.append(f"[{C_DIM}]{escape(item.preview)}[/]")
            lines.append("")
        self.body_text = "\n".join(lines).rstrip()
        try:
            self.query_one("#docs-sidebar-header", Static).update(header_text)
            self._rebuild_options(current_file)
            self._render_recent()
            self._update_preview(current_file)
        except Exception:
            logger.debug("Error updating docs sidebar", exc_info=True)

    def _remember_recent(self, filename: str) -> None:
        clean = str(filename or "").strip()
        if not clean:
            return
        if clean in self._recent_files:
            self._recent_files.remove(clean)
        self._recent_files.insert(0, clean)
        self._recent_files = self._recent_files[:5]

    def _filtered_items(self) -> list[DocNavItem]:
        query = self._query.strip().lower()
        if not query:
            return list(self._all_items)
        filtered: list[DocNavItem] = []
        for item in self._all_items:
            haystack = " ".join([item.filename, item.title, item.preview]).lower()
            if query in haystack:
                filtered.append(item)
        return filtered

    def _rebuild_options(self, current_file: str) -> None:
        option_list = self.query_one("#docs-options", OptionList)
        options: list[Option] = []
        grouped: dict[str, list[DocNavItem]] = {}
        for item in self._filtered_items():
            grouped.setdefault(item.group, []).append(item)

        current_index: int | None = None
        first_selectable: int | None = None
        group_order = ["Research State", "Research Notes", "Role Programs"]
        for group in group_order:
            items = grouped.get(group, [])
            if not items:
                continue
            options.append(Option(f"[bold {C_DIM}]{escape(group)}[/]", disabled=True))
            for item in items:
                active = item.filename == current_file
                color = C_PRIMARY if active else (C_SECONDARY if item.available else C_DIM)
                dynamic_chip = f" {_chip('GEN', fg='#08111a', bg=C_WARNING)}" if item.dynamic else ""
                label = _highlight_match(item.title, self._query, color=C_SKY)
                preview = _highlight_match(item.preview, self._query, color=C_WARNING)
                options.append(
                    Option(
                        f"[{color}]{label}[/]{dynamic_chip}\n[{C_DIM}]{preview}[/]",
                        id=item.filename,
                        disabled=not item.available and not item.dynamic,
                    )
                )
                if first_selectable is None and (item.available or item.dynamic):
                    first_selectable = len(options) - 1
                if active:
                    current_index = len(options) - 1
        option_list.set_options(options)
        option_list.highlighted = current_index if current_index is not None else first_selectable

    def _render_recent(self) -> None:
        recent_widget = self.query_one("#docs-recent", Static)
        if not self._recent_files:
            recent_widget.update(f"[{C_DIM}]No recent docs yet[/]")
            return
        lines = [f"[bold {C_TEXT}]Recent[/]"]
        for filename in self._recent_files[:4]:
            item = self._doc_index.get(filename)
            title = item.title if item else filename
            lines.append(
                f"[{C_PRIMARY}]• {_highlight_match(title, self._query, color=C_SKY)}[/] "
                f"[{C_DIM}]{_highlight_match(filename, self._query, color=C_WARNING)}[/]"
            )
        recent_widget.update("\n".join(lines))

    def _update_preview(self, filename: str) -> None:
        item = self._doc_index.get(filename)
        if item is None:
            return
        chips = []
        if item.available:
            chips.append(_chip("READY", fg="#08111a", bg=C_SECONDARY))
        else:
            chips.append(_chip("MISSING", fg="#08111a", bg=C_DIM))
        if item.dynamic:
            chips.append(_chip("GENERATED", fg="#08111a", bg=C_WARNING))
        preview = (
            f"[bold {C_TEXT}]{_highlight_match(item.title, self._query, color=C_SKY)}[/]  {' '.join(chips)}\n"
            f"[{C_DIM}]{_highlight_match(item.filename, self._query, color=C_WARNING)}[/]\n"
            f"[{C_TEXT}]{_highlight_match(item.preview, self._query, color=C_WARNING)}[/]"
        )
        self.query_one("#docs-preview", Static).update(preview)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "docs-search":
            return
        self._query = event.value
        self._rebuild_options(self._current_file)
        self._render_recent()
        self._update_preview(self._current_file)

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_id:
            self._update_preview(event.option_id)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_id:
            self._current_file = event.option_id
            self.post_message(self.DocRequested(self, event.option_id))


class ExperimentStatusPanel(Static):
    """Live execution focus panel."""

    status_text = reactive("", layout=True)

    def render(self) -> str:
        return self.status_text or "[dim]No active execution yet[/dim]"

    def update_status(
        self,
        activity: dict | None,
        completed: int = 0,
        total: int = 0,
        phase: str = "",
        role_label: str = "Experiment Agent",
    ) -> None:
        if phase == "scouting":
            detail = escape((activity or {}).get("detail", "Analyzing repository, docs, and evaluation path."))
            self.status_text = (
                f"[bold {C_PRIMARY}]Scout Agent[/]\n"
                f"[{C_DIM}]Repository reconnaissance is running.[/]\n"
                f"[{C_TEXT}]{detail}[/]"
            )
            return

        if phase == "reviewing":
            self.status_text = (
                f"[bold {C_WARNING}]Review Gate[/]\n"
                f"[{C_DIM}]Waiting for operator confirmation before the research loop proceeds.[/]"
            )
            return

        if phase == "preparing":
            detail = escape((activity or {}).get("detail", "Installing dependencies, preparing data, and running smoke."))
            self.status_text = (
                f"[bold {C_WARNING}]Repo Prepare[/]\n"
                f"[{C_DIM}]Resolving environment, data, and smoke readiness before research starts.[/]\n"
                f"[{C_TEXT}]{detail}[/]"
            )
            return

        if not activity:
            self.status_text = (
                f"[bold {C_TEXT}]Execution Focus[/]  {_chip('IDLE', fg='#08111a', bg=C_DIM)}\n"
                f"[{C_DIM}]No active role. Waiting for the next manager or experiment cycle.[/]"
            )
            return

        status = str(activity.get("status", "idle") or "idle").strip() or "idle"
        color = _status_color(status)
        label_chip = _chip(_role_label(status), fg="#08111a", bg=color)
        detail = escape(str(activity.get("detail", "")).strip() or "Waiting for input")
        frontier = escape(str(activity.get("frontier_id", "") or activity.get("idea", "")).strip())
        execution = escape(str(activity.get("execution_id", "")).strip())
        progress = ""
        if total > 0:
            bar_width = 24
            filled = min(int(bar_width * completed / max(total, 1)), bar_width)
            progress = f"[{color}]{'█' * filled}{'░' * (bar_width - filled)}[/]  [{C_DIM}]{completed}/{total}[/]"

        lines = [f"[bold {C_TEXT}]Execution Focus[/]  {label_chip}", f"[bold {C_PRIMARY}]{escape(role_label)}[/]"]
        if frontier or execution:
            lines.append(f"[{C_DIM}]{frontier}[/]  [{C_DIM}]{execution}[/]".strip())
        lines.append(f"[{C_TEXT}]{detail}[/]")
        if progress:
            lines.append(progress)
        self.status_text = "\n".join(lines)


class ExecutionSummaryPanel(Static):
    """Execution metrics overview for the execution tab."""

    summary_text = reactive("", layout=True)

    def render(self) -> str:
        return self.summary_text or "[dim]No execution summary yet[/dim]"

    def update_summary(self, summary: ExecutionSummary, *, phase_label: str = "") -> None:
        lines = [
            f"[bold {C_TEXT}]Execution[/]  {_chip(phase_label or 'research-v1', fg='#08111a', bg=C_PRIMARY)}",
            f"[{C_DIM}]metric[/] [{C_TEXT}]{escape(summary.primary_metric or 'metric')}[/]  "
            f"[{C_DIM}]baseline[/] [{C_INFO}]{_format_metric(summary.baseline_value)}[/]  "
            f"[{C_DIM}]current[/] [{C_SECONDARY}]{_format_metric(summary.current_value)}[/]  "
            f"[{C_DIM}]best[/] [bold {C_BEST}]{_format_metric(summary.best_value)}[/]",
            f"[{C_DIM}]results[/] [{C_TEXT}]{summary.total}[/]  "
            f"[{C_SUCCESS}]keep {summary.keep}[/]  "
            f"[{C_WARNING}]discard {summary.discard}[/]  "
            f"[{C_ERROR}]crash {summary.crash}[/]",
        ]
        self.summary_text = "\n".join(lines)


class HotkeyBar(Static):
    """Bottom shortcut bar."""

    bar_text = reactive("")

    def render(self) -> str:
        return self.bar_text or self._build_keys()

    def update_state(self, paused: bool = False, phase: str = "") -> None:
        self.bar_text = self._build_keys(paused=paused, phase=phase)

    @staticmethod
    def _build_keys(paused: bool = False, phase: str = "") -> str:
        keys = [
            f"[bold {C_INFO}]1-4[/] [{C_DIM}]tabs[/]",
            f"[bold {C_INFO}]g[/] [{C_DIM}]gpu[/]",
            f"[bold {C_INFO}]l[/] [{C_DIM}]log[/]",
            f"[bold {C_INFO}]q[/] [{C_DIM}]quit[/]",
        ]
        if paused:
            keys.insert(1, f"[bold {C_SUCCESS}]r[/] [{C_DIM}]resume[/]")
            keys.append(_chip("PAUSED", fg="#08111a", bg=C_CORAL))
        else:
            keys.insert(1, f"[bold {C_INFO}]p[/] [{C_DIM}]pause[/]")
        if phase == "experimenting":
            keys.insert(2, f"[bold {C_INFO}]s[/] [{C_DIM}]skip frontier[/]")
        return "  ".join(keys)


class MetricChart(Static):
    """Experiment metric trend chart using plotext."""

    def compose(self) -> ComposeResult:
        from textual_plotext import PlotextPlot

        yield PlotextPlot(id="plotext-inner")

    def on_mount(self) -> None:
        try:
            from textual_plotext import PlotextPlot

            plot_widget = self.query_one("#plotext-inner", PlotextPlot)
            plot_widget.plt.title("Research Metric")
            plot_widget.refresh()
        except Exception:
            logger.debug("Error initializing metric chart", exc_info=True)

    def update_data(self, rows: list[dict], metric_name: str = "metric") -> None:
        try:
            from textual_plotext import PlotextPlot

            plot_widget = self.query_one("#plotext-inner", PlotextPlot)
        except Exception:
            return

        p = plot_widget.plt
        p.clear_figure()

        if not rows:
            p.title("No experiment data yet")
            plot_widget.refresh()
            return

        values: list[float] = []
        statuses: list[str] = []
        indices: list[int] = []
        for idx, row in enumerate(rows, 1):
            try:
                value = float(row.get("metric_value", ""))
            except (TypeError, ValueError):
                continue
            values.append(value)
            statuses.append(str(row.get("status", "")).strip())
            indices.append(idx)

        if not values:
            p.title("No valid metric data")
            plot_widget.refresh()
            return

        p.plot(indices, values, marker="braille", color="cyan")
        for status, color in [("keep", "green"), ("discard", "yellow"), ("crash", "red")]:
            sx = [indices[i] for i, value in enumerate(statuses) if value == status]
            sy = [values[i] for i, value in enumerate(statuses) if value == status]
            if sx:
                p.scatter(sx, sy, color=color)

        p.hline(values[0], color="blue")
        best = max(values)
        p.hline(best, color="cyan")
        p.title(f"{metric_name} trend")
        p.xlabel("Experiment #")
        p.ylabel(metric_name)
        plot_widget.refresh()


class RecentExperiments(Static):
    """Show the latest experiment rows."""

    results_text = reactive("", layout=True)

    def render(self) -> str:
        return self.results_text or "[dim]No experiments yet[/dim]"

    def update_results(self, rows: list[dict], metric_name: str | None = None) -> None:
        if not rows:
            self.results_text = "[dim]No experiments yet[/dim]"
            return

        title = metric_name or rows[-1].get("primary_metric", "metric")
        lines = [f"[bold {C_TEXT}]Recent Results[/]  [{C_DIM}]{escape(str(title))}[/]"]
        status_style = {"keep": C_SUCCESS, "discard": C_WARNING, "crash": C_ERROR}
        status_icon = {"keep": "↑", "discard": "•", "crash": "×"}

        for row in rows[-6:][::-1]:
            status = str(row.get("status", "?")).strip()
            color = status_style.get(status, C_DIM)
            icon = status_icon.get(status, "?")
            desc = escape(str(row.get("description", "")).strip())[:52]
            value = _format_metric(row.get("metric_value"))
            lines.append(f"[{color}]{icon} {value:>8}[/]  [{C_TEXT}]{desc}[/]")

        self.results_text = "\n".join(lines)


class TraceBanner(Static):
    """Current trace context for the logs page."""

    banner_text = reactive("", layout=True)

    def render(self) -> str:
        return self.banner_text or f"[{C_DIM}]Trace idle — waiting for manager, critic, or experiment events[/]"

    def update_trace(self, text: str) -> None:
        clean = str(text or "").strip()
        if not clean:
            self.banner_text = f"[{C_DIM}]Trace idle — waiting for manager, critic, or experiment events[/]"
            return
        self.banner_text = f"[bold {C_PRIMARY}]Trace[/]  [{C_TEXT}]{escape(clean)}[/]"


def render_ideas_markdown(ideas: list[dict]) -> str:
    """Render the projected backlog as Markdown."""
    if not ideas:
        return "# Projected Backlog\n\n*No projected backlog items yet.*\n"

    def _sort_key(item):
        return (
            int(item.get("priority", 9999) or 9999),
            str(item.get("id", "")),
        )

    lines = [
        "# Projected Backlog",
        "",
        "| Item | Frontier | Description | Category | Priority | Status | Result |",
        "|------|----------|-------------|----------|----------|--------|--------|",
    ]

    counts: dict[str, int] = {}
    for idea in sorted(ideas, key=_sort_key):
        status = str(idea.get("status", "pending"))
        counts[status] = counts.get(status, 0) + 1

        num = str(idea.get("id", "?")).replace("|", "\\|")
        frontier = str(idea.get("frontier_id", "")).replace("|", "\\|")
        desc = str(idea.get("description", "")).replace("|", "\\|")
        if len(desc) > 60:
            desc = desc[:57] + "..."
        category = str(idea.get("category", "")).replace("|", "\\|")
        pri = str(idea.get("priority", ""))
        result = idea.get("result")
        if status == "running":
            result_str = "running..."
        elif isinstance(result, dict):
            verdict = str(result.get("verdict", ""))
            raw_val = result.get("metric_value")
            if raw_val is not None:
                try:
                    result_str = f"{verdict} ({float(raw_val):.4f})"
                except (TypeError, ValueError):
                    result_str = f"{verdict} ({raw_val})"
            else:
                result_str = verdict
        else:
            result_str = ""
        lines.append(
            f"| {num} | {frontier} | {desc} | {category} | {pri} | {status} | {result_str.replace('|', '\\|')} |"
        )

    parts = [f"{counts.get(status, 0)} {status}" for status in ("pending", "running", "done", "skipped") if counts.get(status)]
    lines.append(f"\n**Summary**: {', '.join(parts)}, {len(ideas)} total projected backlog items")
    return "\n".join(lines)


class DocViewer(Static):
    """Document viewer for .research/ markdown files with auto-refresh."""

    DEFAULT_CSS = """
    DocViewer {
        height: 1fr;
    }
    DocViewer #doc-content {
        height: 1fr;
        overflow-y: auto;
    }
    """

    DOC_FILES = [
        "research_graph.md",
        "bootstrap_state.md",
        "research_memory.md",
        "project-understanding.md",
        "literature.md",
        "evaluation.md",
        "research-strategy.md",
        "manager_program.md",
        "critic_program.md",
        "experiment_program.md",
        "projected_backlog.md",
    ]

    DYNAMIC_FILES = {"projected_backlog.md", "research_graph.md", "research_memory.md", "bootstrap_state.md"}
    DEFAULT_FILE = "research_graph.md"

    def __init__(self, research_dir=None, **kwargs):
        super().__init__(**kwargs)
        self.research_dir = research_dir
        self._current_file: str = self.DEFAULT_FILE
        self._last_mtime: float = 0.0
        self._last_content_hash: int = 0

    def compose(self) -> ComposeResult:
        from textual.widgets import Markdown as MarkdownWidget
        from textual.widgets import Select

        options = [(filename, filename) for filename in self.DOC_FILES]
        yield Select(options, value=self.DEFAULT_FILE, id="doc-select")
        yield MarkdownWidget("Select a document to view", id="doc-content")

    async def on_mount(self) -> None:
        await self._load_doc(self.DEFAULT_FILE)
        self.set_interval(5.0, self._schedule_refresh)

    @property
    def current_file(self) -> str:
        return self._current_file

    def _read_content(self, filename: str) -> str:
        if not self.research_dir or not filename:
            return ""
        if filename in self.DYNAMIC_FILES:
            return self._read_dynamic(filename)
        try:
            path = self.research_dir / filename
            if path.exists():
                return path.read_text(encoding="utf-8")
            return f"*File not found: {filename}*"
        except (UnicodeDecodeError, OSError):
            return f"*Error reading: {filename}*"

    def _read_dynamic(self, filename: str) -> str:
        if filename == "projected_backlog.md":
            try:
                from open_researcher.idea_pool import IdeaBacklog

                pool = IdeaBacklog(self.research_dir / "idea_pool.json")
                return render_ideas_markdown(pool.all_ideas())
            except Exception:
                logger.debug("Error reading projected backlog", exc_info=True)
                return "# Projected Backlog\n\n*Error loading projected backlog.*\n"
        if filename == "research_graph.md":
            return self._render_json_markdown(title="Research Graph", source_file="research_graph.json")
        if filename == "bootstrap_state.md":
            return self._render_json_markdown(title="Bootstrap State", source_file="bootstrap_state.json")
        if filename == "research_memory.md":
            return self._render_json_markdown(title="Research Memory", source_file="research_memory.json")
        return ""

    def _render_json_markdown(self, *, title: str, source_file: str) -> str:
        path = self.research_dir / source_file
        if not path.exists():
            return f"# {title}\n\n*File not found: {source_file}*\n"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.debug("Error reading %s", source_file, exc_info=True)
            return f"# {title}\n\n*Error loading {source_file}.*\n"

        if source_file == "research_graph.json":
            summary = [
                f"- hypotheses: {len(payload.get('hypotheses', []))}",
                f"- experiment_specs: {len(payload.get('experiment_specs', []))}",
                f"- frontier: {len(payload.get('frontier', []))}",
                f"- evidence: {len(payload.get('evidence', []))}",
                f"- claim_updates: {len(payload.get('claim_updates', []))}",
            ]
        elif source_file == "bootstrap_state.json":
            steps = payload if isinstance(payload, dict) else {}
            summary = [
                f"- status: {steps.get('status', 'pending')}",
                f"- working_dir: {steps.get('working_dir', '.')}",
                f"- install: {steps.get('install', {}).get('status', 'pending') if isinstance(steps.get('install'), dict) else 'pending'}",
                f"- data: {steps.get('data', {}).get('status', 'pending') if isinstance(steps.get('data'), dict) else 'pending'}",
                f"- smoke: {steps.get('smoke', {}).get('status', 'pending') if isinstance(steps.get('smoke'), dict) else 'pending'}",
            ]
        else:
            summary = [
                f"- repo_type_priors: {len(payload.get('repo_type_priors', []))}",
                f"- ideation_memory: {len(payload.get('ideation_memory', []))}",
                f"- experiment_memory: {len(payload.get('experiment_memory', []))}",
            ]
        pretty = json.dumps(payload, indent=2, ensure_ascii=False)
        return f"# {title}\n\n" + "\n".join(summary) + f"\n\n```json\n{pretty}\n```\n"

    def _get_file_mtime(self, filename: str) -> float:
        if not self.research_dir:
            return 0.0
        if filename == "projected_backlog.md":
            path = self.research_dir / "idea_pool.json"
        elif filename == "research_graph.md":
            path = self.research_dir / "research_graph.json"
        elif filename == "bootstrap_state.md":
            path = self.research_dir / "bootstrap_state.json"
        elif filename == "research_memory.md":
            path = self.research_dir / "research_memory.json"
        else:
            path = self.research_dir / filename
        try:
            return path.stat().st_mtime if path.exists() else 0.0
        except OSError:
            return 0.0

    def _bg_check_refresh(self) -> None:
        filename = self._current_file
        if not filename or not self.research_dir:
            return

        if filename in self.DYNAMIC_FILES:
            content = self._read_content(filename)
            content_hash = hash(content)
            if content_hash == self._last_content_hash:
                return
            self.call_from_thread(self._do_update_content, content, 0.0, content_hash)
            return

        mtime = self._get_file_mtime(filename)
        if mtime == self._last_mtime:
            return
        content = self._read_content(filename)
        content_hash = hash(content)
        self.call_from_thread(self._do_update_content, content, mtime, content_hash)

    def _schedule_refresh(self) -> None:
        self.run_worker(self._bg_check_refresh, thread=True)

    async def _do_update_content(self, content: str, mtime: float, content_hash: int) -> None:
        self._last_mtime = mtime
        self._last_content_hash = content_hash
        try:
            from textual.widgets import Markdown as MarkdownWidget

            md_widget = self.query_one("#doc-content", MarkdownWidget)
            result = md_widget.update(content)
            if result is not None:
                await result
        except Exception:
            logger.debug("Error updating doc content", exc_info=True)

    async def _load_doc(self, filename: str) -> None:
        self._current_file = filename
        self._last_mtime = 0.0
        self._last_content_hash = 0
        content = self._read_content(filename)
        self._last_content_hash = hash(content)
        self._last_mtime = self._get_file_mtime(filename)
        try:
            from textual.widgets import Markdown as MarkdownWidget

            md_widget = self.query_one("#doc-content", MarkdownWidget)
            result = md_widget.update(content)
            if result is not None:
                await result
        except Exception:
            logger.debug("Error updating doc content", exc_info=True)

    async def select_doc(self, filename: str) -> None:
        if not filename:
            return
        if filename not in self.DOC_FILES:
            return
        await self._load_doc(filename)
        try:
            from textual.widgets import Select

            select = self.query_one("#doc-select", Select)
            if select.value != filename:
                select.value = filename
        except Exception:
            logger.debug("Error syncing doc select", exc_info=True)

    async def on_select_changed(self, event) -> None:
        if event.value:
            await self._load_doc(event.value)
