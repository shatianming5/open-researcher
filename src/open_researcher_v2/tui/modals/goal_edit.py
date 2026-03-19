"""Goal edit modal -- available anytime via 'g' key."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Label, Static, TextArea

from open_researcher_v2.state import ResearchState


class GoalEditScreen(Screen):
    """Edit user constraints for the research direction."""

    BINDINGS = [
        Binding("enter", "save", "Save"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, state: ResearchState, **kwargs):
        super().__init__(**kwargs)
        self.state = state
        self._user_text = ""

    def compose(self) -> ComposeResult:
        config = self.state.load_config()
        goal = config.get("metrics", {}).get("primary", {}).get("name", "")
        existing = ""
        path = self.state.dir / "user_constraints.md"
        if path.exists():
            existing = path.read_text(encoding="utf-8")

        with Vertical(id="goal-dialog"):
            yield Label("Edit Research Goal", id="review-title")
            yield Static(f"Primary metric: [bold]{goal}[/]")
            yield Label("\nUser constraints (editable):")
            yield TextArea(existing, id="constraints-edit")
            yield Static("[reverse] enter [/reverse] Save    [reverse] esc [/reverse] Cancel", id="review-actions")

    def on_mount(self) -> None:
        """Auto-focus the constraints editor."""
        self.query_one("#constraints-edit", TextArea).focus()

    def action_save(self) -> None:
        try:
            textarea = self.query_one("#constraints-edit", TextArea)
            self._user_text = textarea.text
        except Exception:
            pass
        if self._user_text.strip():
            path = self.state.dir / "user_constraints.md"
            path.write_text(self._user_text.strip() + "\n", encoding="utf-8")
            self.state.append_log({"event": "goal_updated"})
            try:
                self.app.notify("Goal updated", severity="information")
            except Exception:
                pass
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(None)
