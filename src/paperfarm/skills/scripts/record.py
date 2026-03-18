#!/usr/bin/env python3
"""Record an experiment result to .research/results.tsv."""
import argparse
import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock

FIELDS = [
    "timestamp",
    "worker",
    "frontier_id",
    "status",
    "metric",
    "value",
    "description",
]


def _find_research_dir() -> Path:
    """Walk up from cwd to find .research/ directory."""
    research_dir = Path(".research")
    if research_dir.is_dir():
        return research_dir
    for parent in Path.cwd().parents:
        candidate = parent / ".research"
        if candidate.is_dir():
            return candidate
    print("[ERROR] .research/ directory not found", file=sys.stderr)
    sys.exit(1)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--frontier-id", required=True)
    p.add_argument(
        "--status",
        required=True,
        choices=["keep", "discard", "error", "crash"],
    )
    p.add_argument("--metric", default="")
    p.add_argument("--value", default="")
    p.add_argument("--desc", default="")
    p.add_argument("--worker", default="")
    args = p.parse_args(argv)

    research_dir = _find_research_dir()
    path = research_dir / "results.tsv"
    lock = FileLock(str(path) + ".lock", timeout=10)
    with lock:
        write_header = not path.exists() or path.stat().st_size == 0
        with open(path, "a", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(
                fh,
                fieldnames=FIELDS,
                delimiter="\t",
                extrasaction="ignore",
            )
            if write_header:
                w.writeheader()
            w.writerow(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "worker": args.worker,
                    "frontier_id": args.frontier_id,
                    "status": args.status,
                    "metric": args.metric,
                    "value": args.value,
                    "description": args.desc,
                }
            )
            fh.flush()
            os.fsync(fh.fileno())
    print(f"Recorded: {args.frontier_id} status={args.status} value={args.value}")


if __name__ == "__main__":
    main()
