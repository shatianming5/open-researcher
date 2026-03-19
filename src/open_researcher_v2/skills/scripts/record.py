#!/usr/bin/env python3
"""Record an experiment result to .research/results.tsv.

Called by experiment agents after evaluating a frontier item.
Uses FileLock for concurrent safety in parallel mode.
"""
import argparse
import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from filelock import FileLock
except ImportError:
    # Minimal fallback when filelock is unavailable
    class FileLock:  # type: ignore[no-redef]
        def __init__(self, *a, **kw):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

FIELDS = ["timestamp", "worker", "frontier_id", "status", "metric", "value", "description"]


def _find_research_dir() -> Path:
    """Walk up from cwd to locate the .research directory."""
    candidate = Path(".research")
    if candidate.is_dir():
        return candidate
    for parent in Path.cwd().parents:
        candidate = parent / ".research"
        if candidate.is_dir():
            return candidate
    return Path(".research")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Record experiment result to results.tsv")
    p.add_argument("--frontier-id", required=True, help="Frontier item ID")
    p.add_argument("--status", required=True, choices=["keep", "discard", "error", "crash"],
                   help="Experiment outcome")
    p.add_argument("--metric", default="", help="Metric name")
    p.add_argument("--value", default="", help="Metric value")
    p.add_argument("--desc", default="", help="Short description")
    p.add_argument("--worker", default="", help="Worker ID")
    args = p.parse_args(argv)

    research_dir = _find_research_dir()
    path = research_dir / "results.tsv"
    lock = FileLock(str(path) + ".lock", timeout=10)

    with lock:
        write_header = not path.exists() or path.stat().st_size == 0
        with open(path, "a", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS, delimiter="\t", extrasaction="ignore")
            if write_header:
                w.writeheader()
            w.writerow({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "worker": args.worker,
                "frontier_id": args.frontier_id,
                "status": args.status,
                "metric": args.metric,
                "value": args.value,
                "description": args.desc,
            })
            fh.flush()
            os.fsync(fh.fileno())

    print(f"Recorded: {args.frontier_id} status={args.status} value={args.value}")


if __name__ == "__main__":
    main()
