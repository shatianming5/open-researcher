"""Frontier review modal -- shown after critic preflight."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Label, Static

from .hypothesis import HypothesisReviewScreen


class FrontierReviewScreen(HypothesisReviewScreen):
    """Review critic-assessed frontier items. Same UI as HypothesisReview."""

    def compose(self) -> ComposeResult:
        graph = self.state.load_graph()
        frontier = graph.get("frontier", [])

        with Vertical(id="review-dialog"):
            yield Label("Frontier Review (post-critic)", id="review-title")
            table = DataTable(id="review-table")
            table.add_columns("ID", "P", "Status", "Description", "Keep?")
            table.cursor_type = "row"
            for item in sorted(frontier, key=lambda f: -float(f.get("priority", 0))):
                fid = item.get("id", "")
                keep = "\u2713" if item.get("status") not in ("rejected", "draft") else "\u2717"
                table.add_row(fid, str(item.get("priority", "")),
                              item.get("status", ""), item.get("description", "")[:40], keep)
            yield table
            yield Static("[reverse] space [/reverse] Toggle  [reverse] a [/reverse] Approve all  [reverse] enter [/reverse] Confirm  [reverse] esc [/reverse] Skip", id="review-actions")
