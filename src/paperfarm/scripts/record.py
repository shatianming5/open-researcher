#!/usr/bin/env python3
"""Record an experiment result to .research/results.tsv."""

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from filelock import FileLock

SCALAR_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def get_git_short_hash() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short=7", "HEAD"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return "unknown"
    return result.stdout.strip()


def _coerce_scalar(value: str):
    stripped = value.strip()
    if not stripped:
        return ""
    lowered = stripped.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        if any(ch in stripped for ch in [".", "e", "E"]):
            return float(stripped)
        return int(stripped)
    except ValueError:
        return stripped


def _load_auto_secondary_metrics(
    research_dir: Path,
    *,
    primary_metric: str,
    explicit_secondary: dict,
    override_path: str = "",
) -> dict:
    log_path = Path(override_path) if override_path else None
    if log_path is None:
        env_path = str(os.environ.get("OPEN_RESEARCHER_EVAL_LOG", "")).strip()
        log_path = Path(env_path) if env_path else research_dir / "eval_output.log"
    if not log_path.is_absolute():
        log_path = (Path.cwd() / log_path).resolve()
    if not log_path.exists():
        return {}

    metrics: dict[str, object] = {}
    for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if (
            not key
            or key == primary_metric
            or key in explicit_secondary
            or key.startswith("_open_researcher_")
            or not SCALAR_KEY_RE.match(key)
        ):
            continue
        metrics[key] = _coerce_scalar(value)
    return metrics


def main():
    parser = argparse.ArgumentParser(description="Record experiment result")
    parser.add_argument("--metric", required=True, help="Primary metric name")
    parser.add_argument("--value", required=True, type=float, help="Metric value")
    parser.add_argument("--secondary", default="{}", help="Secondary metrics as JSON")
    parser.add_argument(
        "--secondary-from-log",
        default="",
        help="Optional eval log to auto-harvest scalar key=value metrics from",
    )
    parser.add_argument("--status", required=True, choices=["keep", "discard", "crash"], help="Experiment status")
    parser.add_argument("--desc", required=True, help="Brief description")
    args = parser.parse_args()

    try:
        secondary = json.loads(args.secondary)
    except (json.JSONDecodeError, TypeError):
        print(f"[ERROR] --secondary is not valid JSON: {args.secondary}", file=sys.stderr)
        raise SystemExit(1)
    if not isinstance(secondary, dict):
        print(f"[ERROR] --secondary must decode to a JSON object: {args.secondary}", file=sys.stderr)
        raise SystemExit(1)

    trace = {
        "frontier_id": os.environ.get("OPEN_RESEARCHER_FRONTIER_ID", "").strip(),
        "idea_id": os.environ.get("OPEN_RESEARCHER_IDEA_ID", "").strip(),
        "execution_id": os.environ.get("OPEN_RESEARCHER_EXECUTION_ID", "").strip(),
        "hypothesis_id": os.environ.get("OPEN_RESEARCHER_HYPOTHESIS_ID", "").strip(),
        "experiment_spec_id": os.environ.get("OPEN_RESEARCHER_EXPERIMENT_SPEC_ID", "").strip(),
    }
    trace = {key: value for key, value in trace.items() if value}
    if trace:
        secondary["_open_researcher_trace"] = trace
    secondary["_open_researcher_result_id"] = uuid4().hex

    # Find .research/results.tsv relative to git root
    git_root_result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if git_root_result.returncode != 0:
        print("[ERROR] Failed to determine git root. Are you in a git repository?", file=sys.stderr)
        raise SystemExit(1)
    git_root = git_root_result.stdout.strip()
    research_dir = Path(git_root) / ".research"
    results_path = research_dir / "results.tsv"
    auto_secondary = _load_auto_secondary_metrics(
        research_dir,
        primary_metric=args.metric,
        explicit_secondary=secondary,
        override_path=args.secondary_from_log,
    )
    merged_secondary = dict(auto_secondary)
    merged_secondary.update(secondary)
    secondary = merged_secondary

    header = ["timestamp", "commit", "primary_metric", "metric_value", "secondary_metrics", "status", "description"]

    # Append row
    row = [
        datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        get_git_short_hash(),
        args.metric,
        f"{args.value:.6f}",
        json.dumps(secondary, separators=(",", ":")),
        args.status,
        args.desc,
    ]

    lock = FileLock(str(results_path) + ".lock")
    with lock:
        # Create file with header if it doesn't exist
        if not results_path.exists():
            results_path.parent.mkdir(parents=True, exist_ok=True)
            with results_path.open("w", newline="") as f:
                writer = csv.writer(f, delimiter="\t")
                writer.writerow(header)

        with results_path.open("a", newline="") as f:
            writer = csv.writer(f, delimiter="\t")
            writer.writerow(row)

    print(f"[OK] Recorded: {args.status} | {args.metric}={args.value:.6f} | {args.desc}")


if __name__ == "__main__":
    main()
