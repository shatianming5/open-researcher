"""Custom Textual widgets for Open Researcher TUI — Rich-colored rendering."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widgets import Static


class StatsBar(Static):
    """Top status bar showing experiment summary with Rich color markup."""

    stats_text = reactive("")

    def render(self) -> Text:
        if self.stats_text:
            return Text.from_markup(self.stats_text)
        return Text.from_markup("Open Researcher — starting...")

    def update_stats(self, state: dict) -> None:
        total = state.get("total", 0)
        keep = state.get("keep", 0)
        discard = state.get("discard", 0)
        crash = state.get("crash", 0)
        best = state.get("best_value")
        pm = state.get("primary_metric", "")

        parts: list[str] = ["[bold]Open Researcher[/bold]"]
        if total > 0:
            parts.append(f"{total} exp")
            parts.append(f"[green]{keep} kept[/green]")
            parts.append(f"[red]{discard} disc[/red]")
            if crash:
                parts.append(f"[yellow]{crash} crash[/yellow]")
            if best is not None:
                parts.append(f"[bold cyan]best {pm}={best:.4f}[/bold cyan]")
        else:
            parts.append("[dim]waiting for experiments...[/dim]")

        self.stats_text = " | ".join(parts)


class ExperimentStatusPanel(Static):
    """Prominent display of experiment agent phase with colored icons."""

    status_text = reactive("")

    def render(self) -> Text:
        if self.status_text:
            return Text.from_markup(self.status_text)
        return Text.from_markup("[dim]-- \\[IDLE] waiting to start...[/dim]")

    def update_status(
        self, activity: dict | None, completed: int = 0, total: int = 0
    ) -> None:
        if not activity:
            self.status_text = "[dim]-- \\[IDLE] waiting to start...[/dim]"
            return

        status = activity.get("status", "idle")
        detail = activity.get("detail", "")
        idea = activity.get("idea", "")

        # Phase icon and color mapping
        phase_map: dict[str, tuple[str, str, str]] = {
            "running": ("\u25b6", "green", "RUNNING"),
            "establishing_baseline": ("\u27f3", "yellow", "BASELINE"),
            "paused": ("\u23f8", "yellow", "PAUSED"),
            "idle": ("--", "dim", "IDLE"),
            "analyzing": ("\u25b6", "cyan", "ANALYZING"),
            "generating": ("**", "magenta", "GENERATING"),
            "searching": ("..", "blue", "SEARCHING"),
            "coding": ("<>", "green", "CODING"),
            "evaluating": ("##", "cyan", "EVALUATING"),
            "scheduling": ("::", "yellow", "SCHEDULING"),
            "detecting_gpus": ("||", "blue", "DETECTING_GPUS"),
            "monitoring": ("()", "cyan", "MONITORING"),
            "cpu_serial_mode": ("\\[]", "yellow", "CPU_SERIAL"),
        }

        icon, color, label = phase_map.get(status, ("*", "white", status.upper()))

        lines: list[str] = []
        lines.append(f"  [{color}]{icon} \\[{label}][/{color}]")
        if idea:
            lines.append(f"     [bold]{idea}[/bold]")
        if detail:
            lines.append(f"     [dim]{detail}[/dim]")

        # Progress bar
        if total > 0:
            bar_width = 20
            filled = int(bar_width * completed / total) if total else 0
            empty = bar_width - filled
            bar = "\u2588" * filled + "\u2591" * empty
            lines.append(f"     [{color}]{bar}[/{color}]  {completed}/{total} ideas")

        self.status_text = "\n".join(lines)


class IdeaListPanel(Static):
    """Rich-formatted idea list — each idea is one colored line."""

    ideas_text = reactive("")

    def render(self) -> Text:
        if self.ideas_text:
            return Text.from_markup(self.ideas_text)
        return Text.from_markup("[dim]No ideas yet[/dim]")

    def update_ideas(self, ideas: list[dict]) -> None:
        if not ideas:
            self.ideas_text = "[dim]No ideas yet[/dim]"
            return

        # Show ideas in chronological order (by id number) as a cycle history
        sorted_ideas = sorted(ideas, key=lambda i: i.get("id", "idea-999"))

        lines: list[str] = []
        for cycle, idea in enumerate(sorted_ideas, 1):
            sid = idea.get("status", "pending")
            result = idea.get("result")
            verdict = ""
            if result and isinstance(result, dict):
                verdict = result.get("verdict", "")

            # Truncate description
            desc = idea.get("description", "")
            if len(desc) > 50:
                desc = desc[:47] + "..."

            # Build result string
            if sid == "running":
                icon = "[bold yellow]\u25b6[/bold yellow]"
                result_str = "[bold yellow]running...[/bold yellow]"
            elif sid == "pending":
                icon = "[dim]\u00b7[/dim]"
                result_str = "[dim]pending[/dim]"
            elif verdict == "kept" or (sid == "done" and verdict != "discarded"):
                icon = "[green]\u2713[/green]"
                val = ""
                if result and isinstance(result, dict) and result.get("metric_value"):
                    val = f" val={result['metric_value']:.4f}"
                result_str = f"[green]kept{val}[/green]"
            elif verdict == "discarded":
                icon = "[red]\u2717[/red]"
                val = ""
                if result and isinstance(result, dict) and result.get("metric_value"):
                    val = f" val={result['metric_value']:.4f}"
                result_str = f"[red]disc{val}[/red]"
            elif sid == "skipped":
                icon = "[dim]\u2013[/dim]"
                result_str = "[dim]skipped[/dim]"
            else:
                icon = "[dim]?[/dim]"
                result_str = f"[dim]{sid}[/dim]"

            line = f"  {icon} [bold]Cycle {cycle}[/bold] | {desc}  \u2192 {result_str}"
            lines.append(line)

        self.ideas_text = "\n".join(lines)


class HotkeyBar(Static):
    """Bottom bar showing available keyboard shortcuts with Rich styling."""

    def render(self) -> Text:
        keys = [
            ("[bold cyan]\\[1][/bold cyan][dim]-[/dim][bold cyan]\\[5][/bold cyan][dim]tabs[/dim]"),
            ("[bold cyan]\\[p][/bold cyan][dim]ause[/dim]"),
            ("[bold cyan]\\[r][/bold cyan][dim]esume[/dim]"),
            ("[bold cyan]\\[s][/bold cyan][dim]kip[/dim]"),
            ("[bold cyan]\\[a][/bold cyan][dim]dd idea[/dim]"),
            ("[bold cyan]\\[g][/bold cyan][dim]pu[/dim]"),
            ("[bold cyan]\\[q][/bold cyan][dim]uit[/dim]"),
        ]
        return Text.from_markup(" ".join(keys))


class MetricChart(Static):
    """Experiment metric trend chart using plotext (via textual-plotext)."""

    def compose(self) -> ComposeResult:
        from textual_plotext import PlotextPlot

        yield PlotextPlot(id="plotext-inner")

    def on_mount(self) -> None:
        try:
            from textual_plotext import PlotextPlot

            plot_widget = self.query_one("#plotext-inner", PlotextPlot)
            plot_widget.plt.title("Metric Trend")
            plot_widget.refresh()
        except Exception:
            pass

    def update_data(self, rows: list[dict], metric_name: str = "metric") -> None:
        """Update chart with experiment results."""
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

        values = []
        statuses = []
        for r in rows:
            try:
                values.append(float(r.get("metric_value", 0)))
            except (ValueError, TypeError):
                values.append(0)
            statuses.append(r.get("status", ""))

        x = list(range(1, len(values) + 1))
        p.plot(x, values, marker="braille")

        # Colored scatter by status
        for status, color in [("keep", "green"), ("discard", "red"), ("crash", "yellow")]:
            sx = [x[i] for i, s in enumerate(statuses) if s == status]
            sy = [values[i] for i, s in enumerate(statuses) if s == status]
            if sx:
                p.scatter(sx, sy, color=color)

        # Reference lines
        if values:
            p.hline(values[0], color="blue")  # baseline

        p.title(f"{metric_name} Trend")
        p.xlabel("Experiment #")
        p.ylabel(metric_name)
        plot_widget.refresh()


class RecentExperiments(Static):
    """Shows the last few experiment results with colored status."""

    results_text = reactive("")

    def render(self) -> Text:
        if self.results_text:
            return Text.from_markup(self.results_text)
        return Text.from_markup("[dim]No experiments yet[/dim]")

    def update_results(self, rows: list[dict]) -> None:
        if not rows:
            self.results_text = "[dim]No experiments yet[/dim]"
            return

        lines = ["[bold]Recent Experiments:[/bold]"]
        status_style = {"keep": "green", "discard": "red", "crash": "yellow"}
        status_icon = {"keep": "\u2713", "discard": "\u2717", "crash": "\u2620"}

        for i, r in enumerate(rows[-5:], 1):
            st = r.get("status", "?")
            desc = r.get("description", "")[:40]
            val = r.get("metric_value", "?")
            color = status_style.get(st, "dim")
            icon = status_icon.get(st, "?")
            lines.append(f"  [{color}]{icon} {val}  {desc}[/{color}]")

        self.results_text = "\n".join(lines)


class DocViewer(Static):
    """Document viewer for .research/ markdown files."""

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
        "project-understanding.md",
        "literature.md",
        "evaluation.md",
        "ideas.md",
    ]

    def __init__(self, research_dir=None, **kwargs):
        super().__init__(**kwargs)
        self.research_dir = research_dir

    def compose(self) -> ComposeResult:
        from textual.widgets import Markdown as MarkdownWidget, Select

        options = [(f, f) for f in self.DOC_FILES]
        yield Select(options, value=self.DOC_FILES[0], id="doc-select")
        yield MarkdownWidget("Select a document to view", id="doc-content")

    def on_select_changed(self, event) -> None:
        from textual.widgets import Markdown as MarkdownWidget

        if self.research_dir and event.value:
            path = self.research_dir / event.value
            if path.exists():
                content = path.read_text()
            else:
                content = f"*File not found: {event.value}*"
            try:
                self.query_one("#doc-content", MarkdownWidget).update(content)
            except Exception:
                pass
