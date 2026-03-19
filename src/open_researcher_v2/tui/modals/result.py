"""Result review modal -- shown at end of round."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Label, Static, TextArea
from textual.widgets._data_table import Coordinate
from rich.text import Text

from .base import ReviewScreen


class ResultReviewScreen(ReviewScreen):
    """Review experiment results and optionally override AI keep/discard decisions."""

    BINDINGS = [
        Binding("enter", "confirm", "Confirm"),
        Binding("escape", "skip", "Skip"),
        Binding("space", "toggle_override", "Override"),
    ]

    def __init__(self, state, review_request, **kwargs):
        super().__init__(state=state, review_request=review_request, **kwargs)
        self._overrides: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        results = self.state.load_results()
        config = self.state.load_config()
        baseline_name = config.get("metrics", {}).get("primary", {}).get("name", "metric")

        with Vertical(id="review-dialog"):
            yield Label("Round Results", id="review-title")
            table = DataTable(id="result-table")
            table.add_columns("Frontier", "Value", "AI Decision", "Override?")
            table.cursor_type = "row"
            for r in results[-10:]:
                fid = r.get("frontier_id", "")
                val = r.get("value", "")
                status = r.get("status", "")
                status_style = "bold green" if status == "keep" else "dim" if status == "discard" else "yellow"
                table.add_row(fid, str(val), Text(status, style=status_style), Text("\u2014", style="dim"))
            yield table
            yield Label("\nConstraints for next round:")
            yield TextArea(id="next-constraints")
            yield Static("[reverse] space [/reverse] Override  [reverse] enter [/reverse] Next round  [reverse] esc [/reverse] Skip", id="review-actions")

    # Column index of Override? column (4th column = index 3)
    _OVERRIDE_COL = 3

    def action_toggle_override(self) -> None:
        table: DataTable = self.query_one("#result-table", DataTable)
        row = table.cursor_row
        if row is not None:
            row_key = list(table.rows)[row]
            cells = table.get_row(row_key)
            fid = str(cells[0])
            ai_status = str(cells[2])
            if fid in self._overrides:
                # Toggle off — remove override
                del self._overrides[fid]
                table.update_cell_at(Coordinate(row, self._OVERRIDE_COL), Text("\u2014", style="dim"))
            else:
                new = "keep" if ai_status == "discard" else "discard"
                self._overrides[fid] = new
                if new == "keep":
                    icon = Text("\u2713 keep", style="green")
                else:
                    icon = Text("\u2717 discard", style="red")
                table.update_cell_at(Coordinate(row, self._OVERRIDE_COL), icon)

    def _apply_decisions(self) -> None:
        if self._overrides:
            graph = self.state.load_graph()
            for fid, new_status in self._overrides.items():
                graph.setdefault("claim_updates", []).append({
                    "frontier_id": fid,
                    "new_status": new_status,
                    "reviewer": "human",
                })
                self.state.append_log({
                    "event": "human_override",
                    "frontier_id": fid,
                    "new_status": new_status,
                })
            self.state.save_graph(graph)

        try:
            textarea = self.query_one("#next-constraints", TextArea)
            text = textarea.text.strip()
            if text:
                path = self.state.dir / "user_constraints.md"
                with open(path, "a", encoding="utf-8") as f:
                    f.write(text + "\n")
                self.state.append_log({"event": "goal_updated"})
        except Exception:
            pass
