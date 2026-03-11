"""Implementation of the 'export' command."""

import sys
from pathlib import Path

import yaml

from open_researcher.results_cmd import load_results


def generate_report(repo_path: Path) -> str:
    research = repo_path / ".research"
    config_path = research / "config.yaml"
    if config_path.exists():
        try:
            config = yaml.safe_load(config_path.read_text()) or {}
        except yaml.YAMLError:
            config = {}
    else:
        config = {}
    rows = load_results(repo_path)

    primary = config.get("metrics", {}).get("primary", {})
    metric_name = primary.get("name", "unknown")
    direction = primary.get("direction", "")

    lines = []
    lines.append("# Experiment Report")
    lines.append("")
    lines.append(f"**Primary Metric:** {metric_name} ({direction})")
    lines.append(f"**Total Experiments:** {len(rows)}")
    lines.append("")

    keep_rows = [r for r in rows if r.get("status") == "keep"]
    discard_rows = [r for r in rows if r.get("status") == "discard"]
    crash_rows = [r for r in rows if r.get("status") == "crash"]
    lines.append(f"- Keep: {len(keep_rows)}")
    lines.append(f"- Discard: {len(discard_rows)}")
    lines.append(f"- Crash: {len(crash_rows)}")
    lines.append("")

    lines.append("## Results")
    lines.append("")
    lines.append("| # | Status | Value | Description |")
    lines.append("|---|--------|-------|-------------|")

    def _esc(val: str) -> str:
        """Escape pipe characters in Markdown table cells."""
        return val.replace("|", "\\|")

    for i, row in enumerate(rows, 1):
        lines.append(
            f"| {i} | {_esc(row.get('status', '<missing>'))} "
            f"| {_esc(row.get('metric_value', '<missing>'))} "
            f"| {_esc(row.get('description', '<missing>'))} |"
        )
    lines.append("")

    return "\n".join(lines)


def do_export(repo_path: Path, output: Path | None = None) -> None:
    research = repo_path / ".research"
    if not research.exists():
        print("[ERROR] No .research/ directory found.", file=sys.stderr)
        raise SystemExit(1)

    report = generate_report(repo_path)
    if output is not None:
        output.write_text(report)
    else:
        print(report)
