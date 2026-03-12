"""Review screen — displays Scout Agent analysis for user confirmation."""

from pathlib import Path

import yaml
from textual.app import ComposeResult
from textual.containers import ScrollableContainer, Vertical
from textual.screen import Screen
from textual.widgets import Button, Label, Static, TextArea


def load_review_data(research_dir: Path) -> dict:
    """Load Scout output files for review."""

    def _read(name: str) -> str:
        p = research_dir / name
        if p.exists():
            try:
                return p.read_text()
            except OSError:
                return ""
        return ""

    # Parse metric info from config.yaml
    metric_name = ""
    metric_direction = ""
    config_path = research_dir / "config.yaml"
    if config_path.exists():
        try:
            raw = yaml.safe_load(config_path.read_text()) or {}
            primary = raw.get("metrics", {}).get("primary", {})
            metric_name = primary.get("name", "")
            metric_direction = primary.get("direction", "")
        except (yaml.YAMLError, OSError):
            pass

    return {
        "understanding": _read("project-understanding.md"),
        "strategy": _read("research-strategy.md"),
        "evaluation": _read("evaluation.md"),
        "metric_name": metric_name,
        "metric_direction": metric_direction,
    }


class ReviewScreen(Screen[str | None]):
    """Full-screen review of Scout Agent analysis results."""

    BINDINGS = [
        ("enter", "confirm", "Confirm & Start"),
        ("e", "edit_strategy", "Edit Strategy"),
        ("m", "edit_metrics", "Edit Metrics"),
        ("r", "reanalyze", "Re-analyze"),
        ("q", "cancel", "Quit"),
    ]

    def __init__(self, research_dir: Path):
        super().__init__()
        self.research_dir = research_dir
        self._data = load_review_data(research_dir)

    def compose(self) -> ComposeResult:
        with ScrollableContainer(id="review-container"):
            yield Label("Analysis Complete — Review Research Plan", id="review-title")

            yield Label("Project Understanding", id="section-understanding")
            yield Static(
                self._data["understanding"][:500] or "(No analysis yet)",
                id="understanding-content",
            )

            yield Label("Research Strategy  [e] edit", id="section-strategy")
            yield Static(
                self._data["strategy"] or "(No strategy defined)",
                id="strategy-content",
            )

            yield Label("Evaluation Plan  [m] edit", id="section-evaluation")
            metric_info = ""
            if self._data["metric_name"]:
                metric_info = f"Metric: {self._data['metric_name']} ({self._data['metric_direction']})\n\n"
            yield Static(
                metric_info + (self._data["evaluation"] or "(No evaluation defined)"),
                id="evaluation-content",
            )

        with Vertical(id="review-actions"):
            yield Button("Confirm & Start Research", variant="primary", id="btn-confirm")
            yield Button("Re-analyze", id="btn-reanalyze")
            yield Button("Quit", id="btn-quit")

        yield Static(
            "[bold #7dcfff]\\[Enter][/bold #7dcfff] [dim]Confirm[/dim]  "
            "[bold #7dcfff]\\[e][/bold #7dcfff] [dim]Edit Strategy[/dim]  "
            "[bold #7dcfff]\\[m][/bold #7dcfff] [dim]Edit Metrics[/dim]  "
            "[bold #7dcfff]\\[r][/bold #7dcfff] [dim]Re-analyze[/dim]  "
            "[bold #7dcfff]\\[q][/bold #7dcfff] [dim]Quit[/dim]",
            id="review-footer",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-confirm":
            self.dismiss("confirm")
        elif event.button.id == "btn-reanalyze":
            self.dismiss("reanalyze")
        elif event.button.id == "btn-quit":
            self.dismiss("quit")

    def action_confirm(self) -> None:
        self.dismiss("confirm")

    def action_reanalyze(self) -> None:
        self.dismiss("reanalyze")

    def action_cancel(self) -> None:
        self.dismiss("quit")

    def action_edit_strategy(self) -> None:
        """Open strategy file in an editable TextArea overlay."""
        content = self._data["strategy"]

        def _on_save(new_content: str | None) -> None:
            if new_content is not None:
                (self.research_dir / "research-strategy.md").write_text(new_content)
                self._data["strategy"] = new_content
                try:
                    self.query_one("#strategy-content", Static).update(new_content)
                except Exception:
                    pass

        self.app.push_screen(EditDocScreen(content, "Research Strategy"), _on_save)

    def action_edit_metrics(self) -> None:
        """Open evaluation file in an editable TextArea overlay."""
        content = self._data["evaluation"]

        def _on_save(new_content: str | None) -> None:
            if new_content is not None:
                (self.research_dir / "evaluation.md").write_text(new_content)
                self._data["evaluation"] = new_content
                try:
                    self.query_one("#evaluation-content", Static).update(new_content)
                except Exception:
                    pass

        self.app.push_screen(EditDocScreen(content, "Evaluation Plan"), _on_save)


class EditDocScreen(Screen[str | None]):
    """Simple full-screen text editor for a document."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, content: str, title: str):
        super().__init__()
        self._content = content
        self._title = title

    def compose(self) -> ComposeResult:
        yield Label(f"Editing: {self._title}", id="edit-title")
        yield TextArea(self._content, id="edit-area")
        with Vertical(id="edit-buttons"):
            yield Button("Save", variant="primary", id="btn-save")
            yield Button("Cancel", id="btn-edit-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-save":
            text = self.query_one("#edit-area", TextArea).text
            self.dismiss(text)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
