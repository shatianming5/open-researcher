"""TUI widgets for the Open-Researcher v2 command center.

Each widget exposes an ``update_data`` (or ``update_phase``) method that
accepts plain dicts/lists produced by ``ResearchState.summary()``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from textual.containers import Vertical, VerticalScroll
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
    """Metrics panel with per-metric sparkline area charts and results table."""

    BORDER_TITLE = "Metrics"

    # Bright line colors
    _COLORS = ["#00d7ff", "#00ff87", "#ffd700", "#d787ff", "#5fafff"]
    # Dark fill colors (same hue, much darker for area below curve)
    _COLORS_DIM = ["#004050", "#003820", "#403800", "#301848", "#183050"]

    def compose(self):  # type: ignore[override]
        yield Static(id="metric-summary")
        with VerticalScroll(id="metric-scroll"):
            yield Static(id="metric-chart")
        yield DataTable(id="metric-results")

    def update_data(self, results: list[dict[str, Any]]) -> None:
        summary_w: Static = self.query_one("#metric-summary", Static)
        chart_w: Static = self.query_one("#metric-chart", Static)
        table_w: DataTable = self.query_one("#metric-results", DataTable)

        kept = [r for r in results if r.get("status") == "keep"]
        discarded = [r for r in results if r.get("status") == "discard"]

        # Group kept results by metric name (preserve insertion order)
        metric_data: dict[str, list[float]] = {}
        for r in kept:
            metric = r.get("metric", "") or "value"
            try:
                v = float(r["value"])
            except (ValueError, KeyError, TypeError):
                continue
            metric_data.setdefault(metric, []).append(v)

        if not metric_data:
            summary_w.update("[dim]No kept results yet.[/]")
            chart_w.update("")
            table_w.clear(columns=True)
            return

        # -- Summary line --
        n_metrics = len(metric_data)
        if n_metrics == 1:
            name, vals = next(iter(metric_data.items()))
            best = max(vals)
            latest = vals[-1]
            mean = sum(vals) / len(vals)
            trend = self._trend_arrow(vals)
            summary_w.update(
                f" [dim]Kept: [/][bold]{len(kept)} [/]"
                f"[dim]Disc: [/]{len(discarded)} "
                f"[dim]\u2502 [/]"
                f"[dim]Best: [/][bold cyan]{best:.4f} [/]"
                f"[dim]Mean: [/]{mean:.4f} "
                f"[dim]Latest: [/][bold]{latest:.4f}[/]{trend}"
            )
        else:
            summary_w.update(
                f" [dim]Kept: [/][bold]{len(kept)} [/]"
                f"[dim]Disc: [/]{len(discarded)} "
                f"[dim]\u2502 [/]"
                f"[dim]{n_metrics} metrics tracked[/]"
            )

        # -- Sparkline charts --
        self._render_sparklines(chart_w, metric_data)

        # -- Results table: pivot so each experiment is one row --
        self._update_table(table_w, results, list(metric_data.keys()))

    @staticmethod
    def _update_table(
        table_w: DataTable,
        results: list[dict[str, Any]],
        metric_names: list[str],
    ) -> None:
        """Rebuild table with one column per metric (pivot view)."""
        table_w.clear(columns=True)

        if len(metric_names) <= 1:
            # Single metric or unknown — simple flat table
            table_w.add_columns("#", "Frontier", "Status", "Value", "Worker", "Desc")
            recent = list(reversed(results[-20:]))
            for i, r in enumerate(recent):
                idx = len(results) - i
                status = str(r.get("status", ""))
                style = _STATUS_STYLES.get(status, "white")
                table_w.add_row(
                    str(idx),
                    str(r.get("frontier_id", "")),
                    Text(status, style=style),
                    str(r.get("value", "")),
                    str(r.get("worker", "")),
                    str(r.get("description", ""))[:40],
                )
            return

        # Multi-metric: pivot — group by frontier_id, one column per metric
        table_w.add_columns("#", "Frontier", "Status", *metric_names, "Worker", "Desc")

        # Build pivot: frontier_id → {metric: value, ...}
        pivoted: dict[str, dict[str, str]] = {}
        row_info: dict[str, dict[str, str]] = {}  # frontier_id → status/worker/desc
        order: list[str] = []  # insertion order of frontier_ids

        for r in results:
            fid = r.get("frontier_id", "")
            metric = r.get("metric", "") or "value"
            if fid not in pivoted:
                pivoted[fid] = {}
                order.append(fid)
                row_info[fid] = {
                    "status": str(r.get("status", "")),
                    "worker": str(r.get("worker", "")),
                    "desc": str(r.get("description", ""))[:40],
                }
            pivoted[fid][metric] = str(r.get("value", ""))
            # Update status to latest
            row_info[fid]["status"] = str(r.get("status", ""))

        # Show most recent first, up to 20
        recent_ids = list(reversed(order[-20:]))
        for i, fid in enumerate(recent_ids):
            idx = len(order) - i
            info = row_info[fid]
            status = info["status"]
            style = _STATUS_STYLES.get(status, "white")
            metric_vals = [pivoted[fid].get(m, "") for m in metric_names]
            table_w.add_row(
                str(idx),
                fid,
                Text(status, style=style),
                *metric_vals,
                info["worker"],
                info["desc"],
            )

    @staticmethod
    def _trend_arrow(vals: list[float]) -> str:
        if len(vals) < 2:
            return "\u2192"
        return "\u2191" if vals[-1] > vals[-2] else "\u2193" if vals[-1] < vals[-2] else "\u2192"

    def _render_sparklines(self, widget: Static, metric_data: dict[str, list[float]]) -> None:
        """Render stacked sparkline area charts, one per metric."""
        n_metrics = len(metric_data)
        chart_cols = 90

        # Allocate chart rows per metric
        if n_metrics == 1:
            rows_per = 8
        elif n_metrics == 2:
            rows_per = 5
        elif n_metrics <= 4:
            rows_per = 4
        else:
            rows_per = 3

        colors = self._COLORS
        dim_colors = self._COLORS_DIM
        lines: list[str] = []

        for i, (name, values) in enumerate(metric_data.items()):
            color = colors[i % len(colors)]
            dim_color = dim_colors[i % len(dim_colors)]
            best = max(values)
            latest = values[-1]
            trend = self._trend_arrow(values)

            # Compact metric header
            lines.append(
                f" [{color}]\u25cf {name}  [/]"
                f"[bold {color}]{best:.4f} [/]"
                f"[dim]best  [/]"
                f"[bold]{latest:.4f}[/]{trend} "
                f"[dim]latest  n={len(values)}[/]"
            )

            if len(values) < 2:
                # Single-value mini bar
                lines.append(f"   [{color}]\u2588\u2588\u2588\u2588\u2588[/] {values[0]:.4f}")
            else:
                chart_lines = self._render_area(
                    values, chart_cols, rows_per, color, dim_color,
                )
                lines.extend(chart_lines)

            if i < n_metrics - 1:
                lines.append("")

        widget.update("\n".join(lines))

    # Braille dot positions: (row 0-3, col 0-1) → bitmask
    _DOT_MAP = [
        [0x01, 0x08],
        [0x02, 0x10],
        [0x04, 0x20],
        [0x40, 0x80],
    ]

    @classmethod
    def _render_area(
        cls,
        values: list[float],
        chart_cols: int,
        chart_rows: int,
        color: str,
        dim_color: str,
    ) -> list[str]:
        """Render a braille area chart (4× vertical, 2× horizontal resolution).

        All braille dots at or below the curve are set.  Character cells
        containing the curve boundary use *color* (bright); cells that are
        purely fill below the curve use *dim_color*.
        """
        vmin, vmax = min(values), max(values)
        vrange = vmax - vmin

        if vrange < 1e-9:
            vrange = max(abs(vmin) * 0.1, 0.01)
            vmin -= vrange / 2
            vmax += vrange / 2
            vrange = vmax - vmin
        else:
            pad = vrange * 0.05
            vmin -= pad
            vmax += pad
            vrange = vmax - vmin

        n = len(values)
        px_w = chart_cols * 2   # 2 horizontal pixels per cell
        px_h = chart_rows * 4   # 4 vertical pixels per cell

        # Per-pixel-column height (0 = bottom, px_h-1 = top)
        heights: list[int] = []
        for gx in range(px_w):
            data_x = gx / max(1, px_w - 1) * (n - 1)
            idx = int(data_x)
            frac = data_x - idx
            if idx >= n - 1:
                v = values[-1]
            else:
                v = values[idx] * (1 - frac) + values[idx + 1] * frac
            h = (v - vmin) / vrange * (px_h - 1)
            heights.append(max(0, min(px_h - 1, round(h))))

        dot_map = cls._DOT_MAP
        lines: list[str] = []

        for crow in range(chart_rows):
            # Y-axis label
            if crow == 0:
                label = f"{vmax:.4f} "
            elif crow == chart_rows - 1:
                label = f"{vmin:.4f} "
            else:
                label = " " * 8

            # Build braille characters for this row
            bright_parts: list[str] = []  # chars containing the line
            dim_parts: list[str] = []     # chars that are pure fill
            row_markup: list[str] = []

            for ccol in range(chart_cols):
                code = 0x2800
                has_line = False
                has_any = False

                for dy in range(4):
                    for dx in range(2):
                        # pixel y: 0 = bottom of chart
                        gy = px_h - 1 - (crow * 4 + dy)
                        gx = ccol * 2 + dx
                        if 0 <= gy and gx < px_w:
                            h = heights[gx]
                            if gy <= h:
                                code |= dot_map[dy][dx]
                                has_any = True
                                if gy == h or gy == h - 1:
                                    has_line = True

                ch = chr(code)
                if has_line:
                    row_markup.append(f"[{color}]{ch}[/]")
                elif has_any:
                    row_markup.append(f"[{dim_color}]{ch}[/]")
                else:
                    row_markup.append(" ")

            lines.append(f"[dim]{label}[/]{''.join(row_markup)}")

        return lines
