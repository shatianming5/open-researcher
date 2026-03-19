"""Hypothesis review modal -- shown after manager completes."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Label, Static
from textual.widgets._data_table import Coordinate
from rich.text import Text

from .base import ReviewScreen

_STATUS_COLORS: dict[str, str] = {
    "approved": "green", "running": "cyan", "keep": "bold green",
    "discard": "dim", "archived": "dim", "rejected": "dim red",
    "needs_post_review": "yellow", "draft": "dim",
    "error": "bold red", "crash": "bold red",
}


class HypothesisReviewScreen(ReviewScreen):
    """Review hypotheses and frontier items proposed by manager."""

    BINDINGS = [
        Binding("enter", "confirm", "Confirm"),
        Binding("escape", "skip", "Skip"),
        Binding("space", "toggle_item", "Toggle"),
        Binding("a", "approve_all", "Approve all"),
    ]

    def __init__(self, state, review_request, **kwargs):
        super().__init__(state=state, review_request=review_request, **kwargs)
        self._decisions: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        graph = self.state.load_graph()
        frontier = graph.get("frontier", [])

        with Vertical(id="review-dialog"):
            yield Label("Hypothesis Review", id="review-title")
            table = DataTable(id="review-table")
            table.add_columns("ID", "P", "Status", "Description", "Keep?")
            table.cursor_type = "row"
            for item in sorted(frontier, key=lambda f: -float(f.get("priority", 0))):
                fid = item.get("id", "")
                status = item.get("status", "")
                style = _STATUS_COLORS.get(status, "white")
                is_kept = status != "rejected"
                keep_icon = Text("\u2713", style="green") if is_kept else Text("\u2717", style="red")
                table.add_row(fid, str(item.get("priority", "")),
                              Text(status, style=style), item.get("description", "")[:40], keep_icon)
            yield table
            yield Static("[reverse] space [/reverse] Toggle  [reverse] a [/reverse] Approve all  [reverse] enter [/reverse] Confirm  [reverse] esc [/reverse] Skip", id="review-actions")

    # Column index of Keep? column (5th column = index 4)
    _KEEP_COL = 4

    def action_toggle_item(self) -> None:
        table: DataTable = self.query_one("#review-table", DataTable)
        row = table.cursor_row
        if row is not None:
            row_key = list(table.rows)[row]
            cells = table.get_row(row_key)
            fid = str(cells[0])
            current = self._decisions.get(fid, "approved")
            new_status = "rejected" if current == "approved" else "approved"
            self._decisions[fid] = new_status
            # Update the Keep? column visually
            new_icon = Text("\u2713", style="green") if new_status == "approved" else Text("\u2717", style="red")
            table.update_cell_at(Coordinate(row, self._KEEP_COL), new_icon)

    def action_approve_all(self) -> None:
        self._decisions.clear()
        # Reset all Keep? cells to checkmark
        table: DataTable = self.query_one("#review-table", DataTable)
        for i in range(table.row_count):
            table.update_cell_at(Coordinate(i, self._KEEP_COL), Text("\u2713", style="green"))

    def _apply_decisions(self) -> None:
        if not self._decisions:
            return
        graph = self.state.load_graph()
        for item in graph.get("frontier", []):
            fid = item.get("id", "")
            if fid in self._decisions:
                item["status"] = self._decisions[fid]
        self.state.save_graph(graph)
