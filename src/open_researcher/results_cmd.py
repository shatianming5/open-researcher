"""Implementation of the 'results' command."""

import csv
import json as json_mod
import logging
from pathlib import Path

from filelock import FileLock
from rich.console import Console
from rich.table import Table

from open_researcher.storage import atomic_write_text

logger = logging.getLogger(__name__)


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
            first_line = f.readline()
            if not first_line.strip().startswith("timestamp\t"):
                return []  # missing or corrupted header
            f.seek(0)
            return list(csv.DictReader(f, delimiter="\t"))
    except (OSError, UnicodeDecodeError):
        return []


def _match_result_row(row: dict, *, result_id: str, trace: dict) -> bool:
    secondary = _safe_json_object(row.get("secondary_metrics"))
    if result_id and str(secondary.get("_open_researcher_result_id", "")).strip() == result_id:
        return True
    row_trace = _safe_json_object(secondary.get("_open_researcher_trace"))
    if not trace:
        return False
    for key, expected in trace.items():
        clean_expected = str(expected or "").strip()
        if not clean_expected:
            continue
        if str(row_trace.get(key, "")).strip() != clean_expected:
            return False
    return any(str(value or "").strip() for value in trace.values())


def augment_result_secondary_metrics(repo_path: Path, *, row: dict | None, patch: dict | None) -> bool:
    """Merge additional secondary metrics into an existing results row."""
    if not isinstance(patch, dict) or not patch:
        return False
    results_path = repo_path / ".research" / "results.tsv"
    if not results_path.exists():
        return False

    row_hint = row if isinstance(row, dict) else {}
    hint_secondary = _safe_json_object(row_hint.get("secondary_metrics"))
    result_id = str(hint_secondary.get("_open_researcher_result_id", "")).strip()
    trace = _safe_json_object(hint_secondary.get("_open_researcher_trace"))

    lock = FileLock(str(results_path) + ".lock")
    with lock:
        try:
            with results_path.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle, delimiter="\t")
                fieldnames = list(reader.fieldnames or [])
                rows = list(reader)
        except (OSError, UnicodeDecodeError):
            return False
        if not fieldnames or not rows:
            return False
        required_cols = {"timestamp", "status", "metric_value"}
        if not required_cols.issubset(set(fieldnames)):
            logger.warning("results.tsv schema mismatch: missing %s", required_cols - set(fieldnames))
            return False

        updated = False
        for candidate in reversed(rows):
            if not _match_result_row(candidate, result_id=result_id, trace=trace):
                continue
            secondary = _safe_json_object(candidate.get("secondary_metrics"))
            secondary.update(patch)
            candidate["secondary_metrics"] = json_mod.dumps(secondary, separators=(",", ":"))
            updated = True
            break
        if not updated:
            return False

        import io
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
        atomic_write_text(results_path, buf.getvalue())
    return True


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
        import io as _io
        _row_buf = _io.StringIO()
        _row_writer = csv.writer(_row_buf, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
        _row_writer.writerow(values)
        lines.append(_row_buf.getvalue().rstrip("\r\n"))
    atomic_write_text(repo_path / ".research" / "final_results.tsv", "\n".join(lines) + "\n")


def print_results(repo_path: Path) -> None:
    research = repo_path / ".research"
    if not research.exists():
        Console(stderr=True).print("[red]No .research/ directory found. Run 'open-researcher run' first.[/red]")
        raise SystemExit(1)

    rows = load_results(repo_path)
    if not rows:
        Console().print("[dim]No experiment results yet.[/dim]")
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
        Console().print("[dim]No results to chart.[/dim]")
        return
    if last is not None:
        if last <= 0:
            Console(stderr=True).print("[red]--last must be a positive integer.[/red]")
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
        Console().print("[dim]No valid numeric results to chart.[/dim]")
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
