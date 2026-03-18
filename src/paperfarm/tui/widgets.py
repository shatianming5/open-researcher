"""TUI widgets for the PaperFarm command center.

Each widget exposes an ``update_data`` (or ``update_phase``) method that
accepts plain dicts/lists produced by ``ResearchState.summary()``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from textual.containers import Vertical
from textual.widgets import DataTable, RichLog, Static

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

    def update_data(self, summary: dict[str, Any]) -> None:
        phase = summary.get("phase", "idle")
        rnd = summary.get("round", 0)
        hyps = summary.get("hypotheses", 0)
        done = summary.get("experiments_done", 0)
        total = summary.get("experiments_total", 0)
        running = summary.get("experiments_running", 0)
        best = summary.get("best_value", "\u2014")
        paused = " [PAUSED]" if summary.get("paused") else ""
        self.update(
            f"Phase: {phase} | Round: {rnd} | Hyps: {hyps} "
            f"| Exps: {done}/{total} ({running}) | Best: {best}{paused}"
        )


# ---------------------------------------------------------------------------
# PhaseStripBar
# ---------------------------------------------------------------------------


class PhaseStripBar(Static):
    """Horizontal phase indicator highlighting the active phase in green."""

    def update_phase(self, phase: str) -> None:
        parts: list[str] = []
        for p in _PHASES:
            if p == phase:
                parts.append(f"[bold green]{p.upper()}[/]")
            else:
                parts.append(f"[dim]{p}[/]")
        self.update("  \u2023  ".join(parts))


# ---------------------------------------------------------------------------
# FrontierPanel
# ---------------------------------------------------------------------------


class FrontierPanel(Vertical):
    """DataTable listing frontier items sorted by priority."""

    def compose(self):  # type: ignore[override]
        table = DataTable(id="frontier-table")
        table.add_columns("ID", "Priority", "Status", "Description")
        yield table

    def update_data(self, frontier: list[dict[str, Any]]) -> None:
        table: DataTable = self.query_one("#frontier-table", DataTable)
        table.clear()
        items = sorted(frontier, key=lambda f: -float(f.get("priority", 0)))
        for item in items:
            table.add_row(
                str(item.get("id", "")),
                str(item.get("priority", "")),
                str(item.get("status", "")),
                str(item.get("description", ""))[:60],
            )


# ---------------------------------------------------------------------------
# WorkerPanel
# ---------------------------------------------------------------------------


class WorkerPanel(Vertical):
    """DataTable showing live worker status."""

    def compose(self):  # type: ignore[override]
        table = DataTable(id="worker-table")
        table.add_columns("Worker", "Status", "GPU", "Frontier")
        yield table

    def update_data(self, workers: list[dict[str, Any]]) -> None:
        table: DataTable = self.query_one("#worker-table", DataTable)
        table.clear()
        for w in workers:
            table.add_row(
                str(w.get("id", "")),
                str(w.get("status", "")),
                str(w.get("gpu", "")),
                str(w.get("frontier_id", "")),
            )


# ---------------------------------------------------------------------------
# LogPanel
# ---------------------------------------------------------------------------

_EVENT_PREFIXES: dict[str, str] = {
    "skill_started": "[cyan]SKILL[/]",
    "skill_completed": "[green]DONE[/]",
    "output": "[white]OUT[/]",
    "worker_started": "[blue]W+[/]",
    "worker_finished": "[blue]W-[/]",
    "experiment_result": "[yellow]RES[/]",
}


class LogPanel(Vertical):
    """Append-only rich log display."""

    def compose(self):  # type: ignore[override]
        yield RichLog(id="log-view", highlight=True, markup=True, wrap=True)

    def update_data(self, events: list[dict[str, Any]]) -> None:
        log: RichLog = self.query_one("#log-view", RichLog)
        log.clear()
        for ev in events:
            ts = _ts_short(ev.get("ts", ""))
            etype = ev.get("type", "info")
            prefix = _EVENT_PREFIXES.get(etype, f"[dim]{etype}[/]")
            msg = ev.get("message", ev.get("msg", ""))
            log.write(f"[dim]{ts}[/] {prefix} {msg}")


# ---------------------------------------------------------------------------
# MetricChart
# ---------------------------------------------------------------------------


class MetricChart(Static):
    """Simple text-based chart of kept result values using plotext."""

    def update_data(self, results: list[dict[str, Any]]) -> None:
        kept = [r for r in results if r.get("status") == "keep"]
        if not kept:
            self.update("[dim]No kept results yet.[/]")
            return
        values: list[float] = []
        for r in kept:
            try:
                values.append(float(r["value"]))
            except (ValueError, KeyError, TypeError):
                continue
        if not values:
            self.update("[dim]No numeric results to plot.[/]")
            return
        try:
            import plotext as plt

            plt.clf()
            plt.plot(list(range(1, len(values) + 1)), values, marker="braille")
            plt.title("Metric Trend")
            plt.xlabel("Result #")
            plt.plotsize(60, 8)
            chart = plt.build()
            self.update(chart)
        except ImportError:
            lines = " ".join(f"{v:.4f}" for v in values)
            self.update(f"[dim]Values: {lines}[/]")
