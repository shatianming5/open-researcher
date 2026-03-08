"""Implementation of the 'results' command."""

import csv
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table


def load_results(repo_path: Path) -> list[dict]:
    results_path = repo_path / ".research" / "results.tsv"
    if not results_path.exists():
        return []
    return list(csv.DictReader(results_path.open(), delimiter="\t"))


def print_results(repo_path: Path) -> None:
    research = repo_path / ".research"
    if not research.exists():
        print("[ERROR] No .research/ directory found.", file=sys.stderr)
        raise SystemExit(1)

    rows = load_results(repo_path)
    if not rows:
        print("No experiment results yet.")
        return

    console = Console()
    table = Table(title="Experiment Results")
    table.add_column("#", style="dim")
    table.add_column("Status", style="bold")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_column("Commit", style="dim")
    table.add_column("Description")
    table.add_column("Time", style="dim")

    status_styles = {"keep": "green", "discard": "yellow", "crash": "red"}

    for i, row in enumerate(rows, 1):
        style = status_styles.get(row["status"], "")
        table.add_row(
            str(i),
            row["status"],
            row["primary_metric"],
            row["metric_value"],
            row["commit"],
            row["description"],
            row["timestamp"][:19],
            style=style,
        )

    console.print(table)
