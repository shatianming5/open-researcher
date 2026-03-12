"""Implementation of the 'results' command."""

import csv
import json as json_mod
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from paperfarm.storage import atomic_write_text


def _safe_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_json_object(raw: object) -> dict:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json_mod.loads(raw)
    except (TypeError, ValueError, json_mod.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def load_results(repo_path: Path) -> list[dict]:
    results_path = repo_path / ".research" / "results.tsv"
    if not results_path.exists():
        return []
    try:
        with results_path.open() as f:
            return list(csv.DictReader(f, delimiter="\t"))
    except (OSError, UnicodeDecodeError):
        return []


def derive_final_results(repo_path: Path) -> list[dict]:
    """Overlay critic/evidence verdicts onto raw result rows."""
    rows = load_results(repo_path)
    graph_path = repo_path / ".research" / "research_graph.json"
    if not graph_path.exists():
        return []
    try:
        graph = json_mod.loads(graph_path.read_text())
    except (OSError, ValueError, json_mod.JSONDecodeError):
        return []

    evidence_by_key: dict[tuple[str, str], dict] = {}
    for row in graph.get("evidence", []):
        if not isinstance(row, dict):
            continue
        key = (
            str(row.get("frontier_id", "")).strip(),
            str(row.get("execution_id", "")).strip(),
        )
        if any(key):
            evidence_by_key[key] = row

    claim_by_key: dict[tuple[str, str], dict] = {}
    for row in graph.get("claim_updates", []):
        if not isinstance(row, dict):
            continue
        key = (
            str(row.get("frontier_id", "")).strip(),
            str(row.get("execution_id", "")).strip(),
        )
        if any(key):
            claim_by_key[key] = row

    derived: list[dict] = []
    for row in rows:
        secondary = _safe_json_object(row.get("secondary_metrics"))
        trace = _safe_json_object(secondary.get("_open_researcher_trace"))
        frontier_id = str(trace.get("frontier_id", "")).strip()
        execution_id = str(trace.get("execution_id", "")).strip()
        evidence = evidence_by_key.get((frontier_id, execution_id), {})
        claim = claim_by_key.get((frontier_id, execution_id), {})
        final_status = str(row.get("status", "")).strip()
        evidence_reliability = str(evidence.get("reliability", "")).strip()
        critic_reason_code = ""
        critic_reason = ""
        if claim:
            final_status = str(claim.get("transition", "")).strip() or final_status
            critic_reason_code = str(claim.get("reason_code", "")).strip()
            critic_reason = str(claim.get("reason", "")).strip()
        elif evidence_reliability and evidence_reliability not in {"pending_critic", "strong"}:
            final_status = evidence_reliability
            critic_reason_code = str(evidence.get("reason_code", "")).strip()
        derived.append(
            {
                "timestamp": row.get("timestamp", ""),
                "commit": row.get("commit", ""),
                "primary_metric": row.get("primary_metric", ""),
                "metric_value": row.get("metric_value", ""),
                "raw_status": row.get("status", ""),
                "final_status": final_status,
                "evidence_reliability": evidence_reliability,
                "critic_reason_code": critic_reason_code,
                "critic_reason": critic_reason,
                "description": row.get("description", ""),
                "frontier_id": frontier_id,
                "execution_id": execution_id,
            }
        )
    return derived


def write_final_results_tsv(repo_path: Path) -> None:
    """Write a derived critic-aware results view to .research/final_results.tsv."""
    header = [
        "timestamp",
        "commit",
        "primary_metric",
        "metric_value",
        "raw_status",
        "final_status",
        "evidence_reliability",
        "critic_reason_code",
        "critic_reason",
        "description",
        "frontier_id",
        "execution_id",
    ]
    rows = derive_final_results(repo_path)
    lines = ["\t".join(header)]
    for row in rows:
        values = [str(row.get(key, "")) for key in header]
        escaped = [
            '"' + value.replace('"', '""') + '"' if "\t" in value or "\n" in value else value for value in values
        ]
        lines.append("\t".join(escaped))
    atomic_write_text(repo_path / ".research" / "final_results.tsv", "\n".join(lines) + "\n")


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
        status = row.get("status", "<missing>")
        style = status_styles.get(status, "")
        timestamp = row.get("timestamp", "<missing>")
        table.add_row(
            str(i),
            status,
            row.get("primary_metric", "<missing>"),
            row.get("metric_value", "<missing>"),
            row.get("commit", "<missing>"),
            row.get("description", "<missing>"),
            timestamp[:19] if len(timestamp) >= 19 else timestamp,
            style=style,
        )

    console.print(table)


def print_results_chart(repo_path: Path, metric: str | None = None, last: int | None = None) -> None:
    """Draw a terminal chart showing primary metric over experiment iterations."""
    import plotext as plt

    rows = load_results(repo_path)
    if not rows:
        print("No results to chart.")
        return
    if last is not None:
        if last <= 0:
            print("[ERROR] --last must be a positive integer.", file=sys.stderr)
            raise SystemExit(1)
        rows = rows[-last:]

    # Read config for metric info
    config_path = repo_path / ".research" / "config.yaml"
    try:
        import yaml

        cfg = yaml.safe_load(config_path.read_text()) or {}
        primary = cfg.get("metrics", {}).get("primary", {})
        metric_name = metric or primary.get("name", "metric")
        direction = primary.get("direction", "")
    except (OSError, Exception):
        metric_name = metric or "metric"
        direction = ""

    x: list[int] = []
    values: list[float] = []
    statuses: list[str] = []
    for idx, r in enumerate(rows, 1):
        value = _safe_float(r.get("metric_value"))
        if value is None:
            continue
        x.append(idx)
        values.append(value)
        statuses.append(r.get("status", ""))

    if not values:
        print("No valid numeric results to chart.")
        return

    plt.clear_figure()
    plt.plot(x, values, marker="braille")

    # Colored scatter points by status
    for status, color in [("keep", "green"), ("discard", "yellow"), ("crash", "red")]:
        sx = [x[i] for i, s in enumerate(statuses) if s == status]
        sy = [values[i] for i, s in enumerate(statuses) if s == status]
        if sx:
            plt.scatter(sx, sy, color=color)

    # Reference lines
    if values:
        plt.hline(values[0], color="blue")  # baseline
        if direction == "higher_is_better":
            best = max(values)
        elif direction == "lower_is_better":
            best = min(values)
        else:
            best = max(values)
        plt.hline(best, color="cyan")

    plt.title(f"{metric_name} over experiments")
    plt.xlabel("Experiment #")
    plt.ylabel(metric_name)
    plt.show()


def print_results_json(repo_path: Path) -> None:
    """Output experiment results as JSON."""
    rows = load_results(repo_path)
    print(json_mod.dumps(rows, indent=2))
