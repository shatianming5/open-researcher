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
                self.notify("Description cannot be empty", severity="warning")
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class GoalInputModal(ModalScreen[str | None]):
    """Modal for entering an optional research goal before Scout analysis."""

    BINDINGS = [("escape", "skip", "Skip")]

    def compose(self) -> ComposeResult:
        with Vertical(id="goal-dialog"):
            yield Label("What would you like to optimize?")
            yield Static("Enter a research goal, or press Enter to let the agent decide.", id="goal-hint")
            yield Input(placeholder="e.g., reduce val_loss, improve throughput...", id="goal-input")
            yield Button("Start Analysis", variant="primary", id="btn-start")
            yield Button("Skip (no goal)", id="btn-skip")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-start":
            goal = self.query_one("#goal-input", Input).value.strip()
            self.dismiss(goal if goal else None)
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        goal = event.value.strip()
        self.dismiss(goal if goal else None)

    def action_skip(self) -> None:
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
                reservations = g.get("reservations", []) if isinstance(g.get("reservations"), list) else []
                reserved_mb = sum(int(item.get("memory_mb", 0) or 0) for item in reservations if isinstance(item, dict))
                effective_free = max(int(free or 0) - reserved_mb, 0)
                alloc = ", ".join(
                    str(item.get("tag", "")).strip()
                    for item in reservations
                    if str(item.get("tag", "")).strip()
                )
                status = f"\\[{alloc}]" if alloc else "[#73daca]\\[free][/#73daca]"
                lines.append(
                    f"[#7aa2f7]{host}[/#7aa2f7]:{dev}  "
                    f"{used}/[#bb9af7]{total}[/#bb9af7] MiB  "
                    f"free:[#73daca]{free}[/#73daca] MiB  "
                    f"effective:[#73daca]{effective_free}[/#73daca] MiB  {status}"
                )
            yield Static("\n".join(lines))
            yield Button("Close", id="btn-close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss()

    def action_close(self) -> None:
        self.dismiss()


class LogScreen(Screen):
    """Full-screen log viewer with search."""

    BINDINGS = [("escape", "go_back", "Back"), ("q", "go_back", "Back")]

    def __init__(self, log_path: str):
        super().__init__()
        self.log_path = log_path
        self._all_lines: list[str] = []

    def compose(self) -> ComposeResult:
        import os as _os
        from pathlib import Path

        p = Path(self.log_path)
        if p.exists():
            try:
                CHUNK = 64 * 1024
                with open(p, encoding="utf-8", errors="replace") as f:
                    f.seek(0, _os.SEEK_END)
                    pos = max(f.tell() - CHUNK, 0)
                    f.seek(pos)
                    self._all_lines = f.read().splitlines()[-200:]
            except OSError:
                self._all_lines = ["(Error reading log file)"]
        yield Input(placeholder="Filter logs...", id="log-filter")
        yield TextArea("\n".join(self._all_lines), read_only=True, id="log-content")
        footer = (
            "[bold #7dcfff]\\[Esc][/bold #7dcfff] return  "
            "[bold #7dcfff]\\[q][/bold #7dcfff] quit  "
            "[#8899ab]Type to filter log lines[/#8899ab]"
        )
        yield Static(footer, id="log-footer")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "log-filter":
            return
        query = event.value.strip().lower()
        if not query:
            filtered = self._all_lines
        else:
            filtered = [line for line in self._all_lines if query in line.lower()]
        try:
            self.query_one("#log-content", TextArea).text = "\n".join(filtered)
        except Exception:
            pass

    def action_go_back(self) -> None:
        self.app.pop_screen()
