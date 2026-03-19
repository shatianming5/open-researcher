"""Inject idea modal -- available anytime via 'i' key."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Input, Label, Static

from open_researcher_v2.state import ResearchState


class InjectIdeaScreen(Screen):
    """Inject a human-authored experiment idea into the frontier."""

    BINDINGS = [
        Binding("enter", "inject", "Add to frontier"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, state: ResearchState, **kwargs):
        super().__init__(**kwargs)
        self.state = state
        self._description = ""
        self._priority = 3

    def compose(self) -> ComposeResult:
        with Vertical(id="inject-dialog"):
            yield Label("Inject Experiment", id="review-title")
            yield Label("Description:")
            yield Input(id="inject-desc", placeholder="Describe the experiment...")
            yield Label("Priority (1-5):")
            yield Input(id="inject-priority", value="3")
            yield Static("[reverse] enter [/reverse] Add to frontier    [reverse] esc [/reverse] Cancel", id="review-actions")

    def on_mount(self) -> None:
        """Auto-focus the description input."""
        self.query_one("#inject-desc", Input).focus()

    def _notify(self, message: str, severity: str = "information") -> None:
        try:
            self.app.notify(message, severity=severity)
        except Exception:
            pass

    def action_inject(self) -> None:
        try:
            self._description = self.query_one("#inject-desc", Input).value
            pri_text = self.query_one("#inject-priority", Input).value
        except Exception:
            pri_text = str(self._priority)
        try:
            self._priority = int(pri_text)
        except ValueError:
            self._notify(f"Invalid priority: {pri_text!r}", severity="error")
            return
        if not 1 <= self._priority <= 5:
            self._notify("Priority must be 1-5", severity="error")
            return

        if not self._description.strip():
            self._notify("Description required", severity="error")
            return

        graph = self.state.load_graph()
        counter = graph.get("counters", {}).get("frontier", 0) + 1
        item = {
            "id": f"frontier-{counter:03d}",
            "description": self._description.strip(),
            "priority": self._priority,
            "status": "approved",
            "selection_reason_code": "human_injected",
            "hypothesis_id": "",
            "experiment_spec_id": "",
        }
        graph.setdefault("frontier", []).append(item)
        graph.setdefault("counters", {})["frontier"] = counter
        self.state.save_graph(graph)
        self.state.append_log({"event": "human_injected", "frontier_id": item["id"]})
        try:
            self.app.notify(f"Injected {item['id']}", severity="information")
        except Exception:
            pass
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(None)
