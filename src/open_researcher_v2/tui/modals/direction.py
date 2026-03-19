"""Direction confirmation modal -- shown after scout completes."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label, Static, TextArea

from .base import ReviewScreen


class DirectionConfirmScreen(ReviewScreen):
    """Review and confirm the research direction after scout analysis."""

    def __init__(self, state, review_request, **kwargs):
        super().__init__(state=state, review_request=review_request, **kwargs)
        self._user_constraints = ""

    def compose(self) -> ComposeResult:
        config = self.state.load_config()
        metric = config.get("metrics", {}).get("primary", {})
        metric_name = metric.get("name", "unknown")
        direction = metric.get("direction", "maximize")

        strategy_path = self.state.dir / "research-strategy.md"
        strategy = strategy_path.read_text(encoding="utf-8") if strategy_path.exists() else "[No strategy yet]"

        with Vertical(id="review-dialog"):
            yield Label("Research Direction", id="review-title")
            yield Static(f"Metric: [bold]{metric_name}[/] ({direction})")
            yield Static(f"\n[bold]Strategy:[/]\n{strategy[:500]}")
            yield Label("\nAdditional constraints:")
            yield TextArea(id="constraints-input")
            yield Static("[reverse] enter [/reverse] Confirm & Continue    [reverse] esc [/reverse] Skip", id="review-actions")

    def on_mount(self) -> None:
        """Auto-focus the constraints input."""
        self.query_one("#constraints-input", TextArea).focus()

    def _apply_decisions(self) -> None:
        try:
            textarea = self.query_one("#constraints-input", TextArea)
            self._user_constraints = textarea.text
        except Exception:
            pass
        if self._user_constraints.strip():
            path = self.state.dir / "user_constraints.md"
            with open(path, "a", encoding="utf-8") as f:
                f.write(self._user_constraints.strip() + "\n")
            self.state.append_log({"event": "goal_updated"})
