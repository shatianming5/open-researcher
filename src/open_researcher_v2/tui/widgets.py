"""TUI widgets for the Open-Researcher v2 command center.

Each widget exposes an ``update_data`` (or ``update_phase``) method that
accepts plain dicts/lists produced by ``ResearchState.summary()``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from textual.containers import Vertical
from textual.widgets import DataTable, RichLog, Static
from rich.text import Text

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PHASES = ("scout", "manager", "critic", "experiment")


def _ts_short(iso: str) -> str:
    """Convert an ISO timestamp to a compact ``HH:MM:SS`` string."""
    try:
        dt = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return "??:??:??"
    return dt.strftime("%H:%M:%S")


# ---------------------------------------------------------------------------
# StatsBar
# ---------------------------------------------------------------------------


class StatsBar(Static):
    """Single-line status bar showing key research metrics."""

    _PHASE_COLORS: dict[str, str] = {
        "idle": "dim",
        "scout": "cyan",
        "manager": "green",
        "critic": "yellow",
        "experiment": "magenta",
        "completed": "bold green",
        "failed": "bold red",
        "crashed": "bold red",
    }

    def update_data(self, summary: dict[str, Any]) -> None:
        phase = summary.get("phase", "idle")
        rnd = summary.get("round", 0)
        hyps = summary.get("hypotheses", 0)
        done = summary.get("experiments_done", 0)
        total = summary.get("experiments_total", 0)
        running = summary.get("experiments_running", 0)
        best = summary.get("best_value", "\u2014")
        pc = self._PHASE_COLORS.get(phase, "white")
        suffix = ""
        if summary.get("paused"):
            suffix = "  [bold yellow]\u23f8 PAUSED[/]"
        review = summary.get("awaiting_review")
        if review:
            rtype = review.get("type", "").replace("_", " ").upper()
            suffix = f"  [bold yellow]\u23f3 REVIEW {rtype}[/]"
        self.update(
            f"[dim]Phase:[/] [{pc}]{phase}[/] [dim]|[/] "
            f"[dim]Round:[/] [bold]{rnd}[/] [dim]|[/] "
            f"[dim]Hyps:[/] [bold]{hyps}[/] [dim]|[/] "
            f"[dim]Exps:[/] [bold]{done}/{total}[/] ({running}) [dim]|[/] "
            f"[dim]Best:[/] [bold cyan]{best}[/]{suffix}"
        )


# ---------------------------------------------------------------------------
# PhaseStripBar
# ---------------------------------------------------------------------------


class PhaseStripBar(Static):
    """Horizontal phase indicator highlighting the active phase in green."""

    def update_phase(self, phase: str) -> None:
        parts: list[str] = []
        passed = True
        for p in _PHASES:
            if p == phase:
                parts.append(f"[bold green]\u25b6 {p.upper()}[/]")
                passed = False
            elif phase == "completed":
                # All phases completed
                parts.append(f"[green]\u2713 {p}[/]")
            elif passed and phase not in ("idle", "failed", "crashed"):
                parts.append(f"[green]\u2713 {p}[/]")
            else:
                parts.append(f"[dim]{p}[/]")
        if phase in ("failed", "crashed"):
            parts.append(f"[bold red]\u2717 {phase.upper()}[/]")
        elif phase == "completed":
            parts.append(f"[bold green]\u2713 DONE[/]")
        self.update("  \u2023  ".join(parts))


# ---------------------------------------------------------------------------
# FrontierPanel
# ---------------------------------------------------------------------------


_STATUS_STYLES: dict[str, str] = {
    "approved": "green",
    "running": "cyan",
    "needs_post_review": "yellow",
    "needs_review": "yellow",
    "completed": "bold green",
    "keep": "bold green",
    "discard": "dim",
    "rejected": "dim red",
    "error": "bold red",
    "crash": "bold red",
    "draft": "dim",
}


class FrontierPanel(Vertical):
    """DataTable listing frontier items sorted by priority."""

    BORDER_TITLE = "Frontier"

    def compose(self):  # type: ignore[override]
        table = DataTable(id="frontier-table")
        table.add_columns("ID", "Pri", "Status", "Description")
        yield table

    @staticmethod
    def _safe_priority(item: dict) -> float:
        try:
            return float(item.get("priority", 0))
        except (ValueError, TypeError):
            return 0.0

    def update_data(self, frontier: list[dict[str, Any]]) -> None:
        table: DataTable = self.query_one("#frontier-table", DataTable)
        table.clear()
        items = sorted(frontier, key=lambda f: -self._safe_priority(f))
        for item in items:
            status = str(item.get("status", ""))
            style = _STATUS_STYLES.get(status, "white")
            table.add_row(
                str(item.get("id", "")),
                str(item.get("priority", "")),
                Text(status, style=style),
                str(item.get("description", ""))[:60],
            )


# ---------------------------------------------------------------------------
# WorkerPanel
# ---------------------------------------------------------------------------


class WorkerPanel(Vertical):
    """DataTable showing live worker status."""

    BORDER_TITLE = "Workers"

    def compose(self):  # type: ignore[override]
        table = DataTable(id="worker-table")
        table.add_columns("Worker", "Status", "GPU", "Frontier")
        yield table

    def update_data(self, workers: list[dict[str, Any]]) -> None:
        table: DataTable = self.query_one("#worker-table", DataTable)
        table.clear()
        for w in workers:
            status = str(w.get("status", ""))
            style = _STATUS_STYLES.get(status, "white")
            table.add_row(
                str(w.get("id", "")),
                Text(status, style=style),
                str(w.get("gpu", "")),
                str(w.get("frontier_id", "")),
            )


# ---------------------------------------------------------------------------
# LogPanel
# ---------------------------------------------------------------------------

_EVENT_PREFIXES: dict[str, str] = {
    "skill_started": "[cyan]SKILL[/]",
    "skill_completed": "[green]DONE [/]",
    "output": "[white]OUT  [/]",
    "worker_started": "[blue]W+   [/]",
    "worker_finished": "[blue]W-   [/]",
    "experiment_result": "[yellow]RES  [/]",
    "review_requested": "[bold yellow]WAIT [/]",
    "review_completed": "[green]REVW [/]",
    "review_timeout": "[yellow]TOUT [/]",
    "review_skipped": "[dim]SKIP [/]",
    "human_injected": "[bold cyan]INJ  [/]",
    "human_override": "[bold magenta]OVRD [/]",
    "goal_updated": "[cyan]GOAL [/]",
}


class LogPanel(Vertical):
    """Append-only rich log display."""

    BORDER_TITLE = "Logs"

    def compose(self):  # type: ignore[override]
        yield RichLog(id="log-view", highlight=True, markup=True, wrap=True)

    def update_data(self, events: list[dict[str, Any]]) -> None:
        log: RichLog = self.query_one("#log-view", RichLog)
        log.clear()
        for ev in events:
            ts = _ts_short(ev.get("ts", ""))
            etype = ev.get("event", ev.get("type", "info"))
            prefix = _EVENT_PREFIXES.get(etype, f"[dim]{etype}[/]")
            msg = ev.get("message", ev.get("msg", ev.get("line", "")))
            log.write(f"[dim]{ts}[/] {prefix} [dim]│[/] {msg}")


# ---------------------------------------------------------------------------
# MetricChart
# ---------------------------------------------------------------------------


class MetricChart(Vertical):
    """Metrics panel with summary stats, trend chart, and results table."""

    BORDER_TITLE = "Metrics"

    def compose(self):  # type: ignore[override]
        yield Static(id="metric-summary")
        yield Static(id="metric-chart")
        table = DataTable(id="metric-results")
        table.add_columns("#", "Frontier", "Status", "Metric", "Value", "Worker", "Desc")
        yield table

    def update_data(self, results: list[dict[str, Any]]) -> None:
        summary_w: Static = self.query_one("#metric-summary", Static)
        chart_w: Static = self.query_one("#metric-chart", Static)
        table_w: DataTable = self.query_one("#metric-results", DataTable)

        kept = [r for r in results if r.get("status") == "keep"]
        discarded = [r for r in results if r.get("status") == "discard"]

        # Extract numeric values from kept results
        values: list[float] = []
        for r in kept:
            try:
                values.append(float(r["value"]))
            except (ValueError, KeyError, TypeError):
                continue

        # -- Summary line --
        if not values:
            summary_w.update("[dim]No kept results yet.[/]")
            chart_w.update("")
            table_w.clear()
            return

        best = max(values)
        worst = min(values)
        latest = values[-1]
        mean = sum(values) / len(values)
        if len(values) >= 2:
            trend = "\u2191" if values[-1] > values[-2] else "\u2193" if values[-1] < values[-2] else "\u2192"
        else:
            trend = "\u2192"

        summary_w.update(
            f" [dim]Kept:[/][bold]{len(kept)}[/] "
            f"[dim]Disc:[/]{len(discarded)} "
            f"[dim]\u2502[/] "
            f"[dim]Best:[/][bold cyan]{best:.4f}[/] "
            f"[dim]Mean:[/]{mean:.4f} "
            f"[dim]Latest:[/][bold]{latest:.4f}[/]{trend}"
        )

        # -- Chart --
        self._render_chart(chart_w, values)

        # -- Results table (most recent first, up to 20 rows) --
        table_w.clear()
        recent = list(reversed(results[-20:]))
        for i, r in enumerate(recent):
            idx = len(results) - i
            status = str(r.get("status", ""))
            style = _STATUS_STYLES.get(status, "white")
            table_w.add_row(
                str(idx),
                str(r.get("frontier_id", "")),
                Text(status, style=style),
                str(r.get("metric", "")),
                str(r.get("value", "")),
                str(r.get("worker", "")),
                str(r.get("description", ""))[:40],
            )

    @staticmethod
    def _render_chart(widget: Static, values: list[float]) -> None:
        """Render a Unicode block chart into the given Static widget."""
        if not values:
            widget.update("")
            return

        _BLOCKS = " \u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"
        rows = 8
        vmin, vmax = min(values), max(values)
        vrange = vmax - vmin
        if vrange < 1e-9:
            # Flat data — show a single mid-height bar
            widget.update(
                f"[dim]  {vmin:.4f} [/][dim]\u2502[/]"
                f"[cyan]{'\u2584' * min(len(values) * 2, 80)}[/]"
            )
            return

        n = len(values)
        # Bar width: aim for ~100 chars total chart area
        bar_w = max(1, min(6, 100 // n))

        # Y-axis labels: show at top, middle, bottom rows
        y_positions = {rows - 1: vmax, rows // 2: (vmin + vmax) / 2, 0: vmin}

        lines = []
        for row in range(rows - 1, -1, -1):
            # Y-axis label
            if row in y_positions:
                label = f"{y_positions[row]:.4f}"
            else:
                label = ""
            parts = [f"[dim]{label:>7} \u2502[/]"]

            for v in values:
                normalized = (v - vmin) / vrange * rows * 8
                row_fill = normalized - row * 8
                if row_fill >= 8:
                    ch = _BLOCKS[8]
                elif row_fill >= 1:
                    ch = _BLOCKS[int(row_fill)]
                elif row_fill > 0:
                    ch = _BLOCKS[1]
                else:
                    ch = " "
                if ch != " ":
                    parts.append(f"[cyan]{ch * bar_w}[/]")
                else:
                    parts.append(" " * bar_w)

            lines.append("".join(parts))

        # X-axis line
        chart_w = bar_w * n
        lines.append(f"[dim]{' ' * 8}\u2514{'─' * chart_w}[/]")

        # X-axis labels (sparse to avoid crowding)
        if n <= 20:
            step = 1
        elif n <= 50:
            step = max(1, n // 15)
        else:
            step = max(1, n // 10)

        x_parts = [" " * 9]
        for i in range(n):
            num = i + 1
            if num == 1 or num == n or num % step == 0:
                x_parts.append(f"[dim]{str(num).center(bar_w)}[/]")
            else:
                x_parts.append(" " * bar_w)
        lines.append("".join(x_parts))

        widget.update("\n".join(lines))
