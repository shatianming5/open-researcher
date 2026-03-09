"""Modal screens for Open Researcher TUI."""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Input, Label, Select, Static, TextArea


class AddIdeaModal(ModalScreen[dict | None]):
    """Modal dialog for adding a new idea to the pool."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Add New Idea")
            yield Input(placeholder="Idea description...", id="idea-desc")
            yield Select(
                [(c, c) for c in ["general", "architecture", "training", "data", "regularization", "infrastructure"]],
                value="general",
                id="idea-category",
            )
            yield Input(placeholder="Priority (1=highest)", id="idea-priority", value="5")
            yield Button("Add", variant="primary", id="btn-add")
            yield Button("Cancel", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-add":
            desc = self.query_one("#idea-desc", Input).value.strip()
            if desc:
                cat = self.query_one("#idea-category", Select).value
                try:
                    pri = int(self.query_one("#idea-priority", Input).value)
                except ValueError:
                    pri = 5
                self.dismiss({"description": desc, "category": cat, "priority": pri})
            else:
                self.dismiss(None)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class GPUStatusModal(ModalScreen):
    """Modal showing GPU status across all hosts."""

    BINDINGS = [("escape", "close", "Close")]

    def __init__(self, gpus: list[dict]):
        super().__init__()
        self.gpus = gpus

    def compose(self) -> ComposeResult:
        with Vertical(id="gpu-dialog"):
            yield Label("GPU Status")
            lines = []
            if not self.gpus:
                lines.append("No GPUs detected")
            for g in self.gpus:
                host = g.get("host", "?")
                dev = g.get("device", "?")
                total = g.get("memory_total", 0)
                used = g.get("memory_used", 0)
                free = g.get("memory_free", 0)
                alloc = g.get("allocated_to", None)
                status = f"\\[{alloc}]" if alloc else "\\[free]"
                lines.append(f"{host}:{dev}  {used}/{total} MiB  free:{free} MiB  {status}")
            yield Static("\n".join(lines))
            yield Button("Close", id="btn-close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss()

    def action_close(self) -> None:
        self.dismiss()


class LogScreen(Screen):
    """Full-screen log viewer."""

    BINDINGS = [("escape", "go_back", "Back"), ("q", "go_back", "Back")]

    def __init__(self, log_path: str):
        super().__init__()
        self.log_path = log_path

    def compose(self) -> ComposeResult:
        from pathlib import Path

        content = ""
        p = Path(self.log_path)
        if p.exists():
            lines = p.read_text().splitlines()
            content = "\n".join(lines[-200:])
        yield TextArea(content, read_only=True, id="log-content")
        yield Static("Press \\[Esc] or \\[q] to return", id="log-footer")

    def action_go_back(self) -> None:
        self.app.pop_screen()
