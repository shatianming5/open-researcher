"""TUI widgets for the Open-Researcher v2 command center.

Each widget exposes an ``update_data`` (or ``update_phase``) method that
accepts plain dicts/lists produced by ``ResearchState.summary()``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from textual.containers import Vertical, VerticalScroll
from textual.widgets import DataTable, RichLog, Static
from rich.console import Group
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
    """Metrics panel with per-metric line charts and results table."""

    BORDER_TITLE = "Metrics"

    # Vibrant, distinct line colors for up to 10 metrics
    _COLORS = [
        "#00d7ff", "#00ff87", "#ffd700", "#ff5f87", "#af87ff",
        "#5fd7ff", "#87d700", "#ffaf00", "#d75f87", "#875fff",
    ]

    # Metric name patterns where lower is better
    _MINIMIZE_PATTERNS = (
        "loss", "error", "perp", "mse", "mae", "cer", "wer", "fer",
    )

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
        # Textual strips whitespace at style boundaries.  Use NBSP (\xa0)
        # inside styled spans so spaces survive rendering.
        S = "\xa0"  # non-breaking space
        n_metrics = len(metric_data)
        if n_metrics == 1:
            name, vals = next(iter(metric_data.items()))
            lo_better = self._is_minimize(name)
            best = min(vals) if lo_better else max(vals)
            latest = vals[-1]
            mean = sum(vals) / len(vals)
            trend = self._trend_arrow(vals, lo_better)
            t = Text()
            t.append(f" {len(kept)}{S}", style="bold")
            t.append(f"kept{S}\u00b7{S}{len(discarded)}{S}disc{S}\u2502{S}", style="dim")
            t.append(f"best{S}", style="dim")
            t.append(f"{best:.4f}{S}", style="bold cyan")
            t.append(f"\u00b7{S}mean{S}", style="dim")
            t.append(f"{mean:.4f}{S}", style="")
            t.append(f"\u00b7{S}latest{S}", style="dim")
            t.append(f"{latest:.4f}{S}", style="bold")
            t.append_text(Text.from_markup(trend))
            summary_w.update(t)
        else:
            t = Text()
            t.append(f" {len(kept)}{S}", style="bold")
            t.append(f"kept{S}\u00b7{S}{len(discarded)}{S}disc{S}\u2502{S}", style="dim")
            t.append(f"{n_metrics}{S}", style="bold")
            t.append("metrics", style="dim")
            summary_w.update(t)

        # -- Line charts --
        self._render_charts(chart_w, metric_data)

        # -- Results table: pivot so each experiment is one row --
        self._update_table(table_w, results, list(metric_data.keys()))

    # -- Table ---------------------------------------------------------------

    @staticmethod
    def _update_table(
        table_w: DataTable,
        results: list[dict[str, Any]],
        metric_names: list[str],
    ) -> None:
        """Rebuild table with one column per metric (pivot view)."""
        table_w.clear(columns=True)

        if len(metric_names) <= 1:
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

        table_w.add_columns("#", "Frontier", "Status", *metric_names, "Worker", "Desc")

        pivoted: dict[str, dict[str, str]] = {}
        row_info: dict[str, dict[str, str]] = {}
        order: list[str] = []

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
            row_info[fid]["status"] = str(r.get("status", ""))

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

    # -- Helpers -------------------------------------------------------------

    @classmethod
    def _is_minimize(cls, name: str) -> bool:
        """Heuristic: lower is better for loss/error style metrics."""
        return any(p in name.lower() for p in cls._MINIMIZE_PATTERNS)

    @staticmethod
    def _trend_arrow(vals: list[float], lower_is_better: bool = False) -> str:
        """Return a colored trend arrow with trailing padding inside the tag.

        Trailing spaces live inside the markup tag to survive Textual's
        post-[/] whitespace stripping.
        """
        if len(vals) < 2:
            return ""
        diff = vals[-1] - vals[-2]
        if abs(diff) < 1e-9:
            return "[dim]\u2192  [/]"
        improving = (diff < 0) if lower_is_better else (diff > 0)
        if improving:
            arrow = "\u2193" if lower_is_better else "\u2191"
            return f"[green]{arrow}  [/]"
        arrow = "\u2191" if lower_is_better else "\u2193"
        return f"[red]{arrow}  [/]"

    # -- Chart rendering -----------------------------------------------------

    def _render_charts(
        self, widget: Static, metric_data: dict[str, list[float]]
    ) -> None:
        """Render stacked line charts, one per metric."""
        n_metrics = len(metric_data)
        chart_cols = 92

        if n_metrics == 1:
            rows_per = 8
        elif n_metrics == 2:
            rows_per = 6
        elif n_metrics <= 4:
            rows_per = 4
        else:
            rows_per = 3

        parts: list[Text | str] = []

        for i, (name, values) in enumerate(metric_data.items()):
            color = self._COLORS[i % len(self._COLORS)]
            lo_better = self._is_minimize(name)
            best = min(values) if lo_better else max(values)
            latest = values[-1]
            trend = self._trend_arrow(values, lo_better)

            # Legend header: colored dash + name + stats
            # Use NBSP (\xa0) at style boundaries to survive Textual stripping
            S = "\xa0"
            padded_name = name.ljust(22)
            header = Text(f"  ")
            header.append(f"\u2500\u2500{S}", style=color)
            header.append(f"{padded_name}", style=f"bold {color}")
            header.append(f"best{S}", style="dim")
            header.append(f"{best:.4f}{S}{S}", style=f"bold {color}")
            header.append(f"latest{S}", style="dim")
            header.append(f"{latest:.4f}{S}", style="bold")
            header.append_text(Text.from_markup(trend))
            header.append(f"n={len(values)}", style="dim")
            parts.append(header)

            if len(values) < 2:
                parts.append(
                    f"    [{color}]\u2501\u2501\u2501\u2501\u2501"
                    f"\u2501\u2501\u2501\u2501\u2501 [/]{values[0]:.4f}"
                )
            else:
                chart_lines = self._render_line_chart(
                    values, chart_cols, rows_per, color,
                )
                parts.append("\n".join(chart_lines))

            if i < n_metrics - 1:
                parts.append("")

        widget.update(Group(*parts))

    # Braille dot positions: (row 0-3, col 0-1) → bitmask
    _DOT_MAP = [
        [0x01, 0x08],
        [0x02, 0x10],
        [0x04, 0x20],
        [0x40, 0x80],
    ]

    @classmethod
    def _render_line_chart(
        cls,
        values: list[float],
        chart_cols: int,
        chart_rows: int,
        color: str,
    ) -> list[str]:
        """Render a clean braille line chart (no area fill).

        Only the curve itself is drawn (with vertical connections between
        consecutive pixel columns for continuity).  A dim Y-axis is shown
        on the left with value labels at top, middle, and bottom.
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
        px_w = chart_cols * 2  # 2 horizontal pixels per braille cell
        px_h = chart_rows * 4  # 4 vertical pixels per braille cell

        # Interpolate data values to pixel-column heights
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

        # Build pixel set — 2px-thick line for visual weight
        pixels: set[tuple[int, int]] = set()
        for gx in range(px_w):
            h = heights[gx]
            pixels.add((gx, h))
            # Thicken: add one pixel below the curve
            if h > 0:
                pixels.add((gx, h - 1))
            # Vertical connection to previous column for continuity
            if gx > 0:
                prev_h = heights[gx - 1]
                lo, hi = min(h, prev_h), max(h, prev_h)
                for gy in range(lo, hi + 1):
                    pixels.add((gx, gy))

        dot_map = cls._DOT_MAP
        lines: list[str] = []

        # Determine which rows get a Y-axis value label
        mid_row = chart_rows // 2
        label_rows: dict[int, float] = {
            0: vmax,
            chart_rows - 1: vmin,
        }
        if chart_rows >= 5:
            label_rows[mid_row] = (vmin + vmax) / 2

        for crow in range(chart_rows):
            # Y-axis value label (right-aligned, 8 chars)
            if crow in label_rows:
                label = f"{label_rows[crow]:>8.3f}"
            else:
                label = " " * 8

            # Build braille characters for this cell row
            row_chars: list[str] = []
            for ccol in range(chart_cols):
                code = 0x2800
                has_dot = False

                for dy in range(4):
                    for dx in range(2):
                        gy = px_h - 1 - (crow * 4 + dy)
                        gx = ccol * 2 + dx
                        if (
                            0 <= gy < px_h
                            and 0 <= gx < px_w
                            and (gx, gy) in pixels
                        ):
                            code |= dot_map[dy][dx]
                            has_dot = True

                ch = chr(code)
                if has_dot:
                    row_chars.append(f"[{color}]{ch}[/]")
                else:
                    row_chars.append(" ")

            lines.append(
                f"  [dim]{label} \u2502[/]{''.join(row_chars)}"
            )

        return lines
