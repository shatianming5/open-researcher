"""Implementation of the 'status' command."""

import csv
import json
import math
import subprocess
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from open_researcher.config import RESEARCH_PROTOCOL, ResearchConfig, load_config
from open_researcher.research_graph import ResearchGraphStore


def _safe_float(value: str) -> float | None:
    """Parse a string to float, returning None for non-numeric or NaN values."""
    try:
        v = float(value)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except (ValueError, TypeError):
        return None


def _has_real_content(path: Path) -> bool:
    """Check if a markdown file has real content beyond headings and comments."""
    if not path.exists():
        return False
    content = path.read_text()
    if "<!--" in content and content.strip().endswith("-->"):
        return False
    return any(
        line.strip()
        and not line.strip().startswith("#")
        and not line.strip().startswith(">")
        and "<!--" not in line
        and not line.strip().startswith("|")
        for line in content.splitlines()
    )


def _detect_phase(research: Path) -> int:
    """Detect current research phase (1-5) based on file contents."""
    pu = research / "project-understanding.md"
    lit = research / "literature.md"
    ev = research / "evaluation.md"
    results = research / "results.tsv"
    bootstrap = _load_bootstrap_state(research)

    # Phase 1: project understanding not filled
    if not _has_real_content(pu):
        return 1

    # Phase 2: literature review not filled
    if not _has_real_content(lit):
        return 2

    # Phase 3: evaluation not filled
    if not _has_real_content(ev):
        return 3

    # Phase 4: repo prepare/bootstrap
    if bootstrap and bootstrap.get("status") not in {"completed", "disabled"}:
        return 4

    # Phase 5/6: check results
    if results.exists():
        with results.open() as f:
            rows = list(csv.DictReader(f, delimiter="\t"))
        if len(rows) == 0:
            return 5
        return 6

    return 5


def _safe_list_field(payload: dict, key: str) -> list:
    value = payload.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    return value


def _load_graph_state(research: Path) -> dict | None:
    graph_path = research / "research_graph.json"
    if not graph_path.exists():
        return None
    try:
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": f"Parse error: {exc}"}
    if not isinstance(graph, dict):
        return {"error": "top-level JSON must be an object"}

    try:
        frontier = _safe_list_field(graph, "frontier")
        hypotheses = _safe_list_field(graph, "hypotheses")
        experiment_specs = _safe_list_field(graph, "experiment_specs")
        evidence = _safe_list_field(graph, "evidence")
        claim_updates = _safe_list_field(graph, "claim_updates")
    except ValueError as exc:
        return {"error": str(exc)}

    status_counts: dict[str, int] = {}
    for row in frontier:
        if not isinstance(row, dict):
            continue
        status = str(row.get("status", "")).strip() or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1

    return {
        "version": str(graph.get("version", "")),
        "hypotheses": len(hypotheses),
        "experiment_specs": len(experiment_specs),
        "evidence": len(evidence),
        "claim_updates": len(claim_updates),
        "frontier_total": len(frontier),
        "frontier_status_counts": status_counts,
        "frontier_runnable": sum(
            status_counts.get(status, 0)
            for status in ResearchGraphStore.EXECUTABLE_FRONTIER_STATUSES
        ),
    }


def _load_bootstrap_state(research: Path) -> dict | None:
    path = research / "bootstrap_state.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": f"Parse error: {exc}"}
    if not isinstance(payload, dict):
        return {"error": "top-level JSON must be an object"}
    steps = {}
    for step_name in ("install", "data", "smoke"):
        value = payload.get(step_name, {})
        if not isinstance(value, dict):
            return {"error": f"{step_name} must be an object"}
        steps[step_name] = {
            "status": str(value.get("status", "")).strip(),
            "command": str(value.get("command", "")).strip(),
            "source": str(value.get("source", "")).strip(),
        }
    errors = payload.get("errors", [])
    if not isinstance(errors, list):
        return {"error": "errors must be a list"}
    unresolved = payload.get("unresolved", [])
    if not isinstance(unresolved, list):
        return {"error": "unresolved must be a list"}
    expected_status = payload.get("expected_path_status", [])
    if not isinstance(expected_status, list):
        return {"error": "expected_path_status must be a list"}
    return {
        "status": str(payload.get("status", "")).strip() or "pending",
        "working_dir": str(payload.get("working_dir", ".") or "."),
        "python_executable": str(payload.get("python_env", {}).get("executable", "")).strip()
        if isinstance(payload.get("python_env"), dict)
        else "",
        "requires_gpu": bool(payload.get("requires_gpu", False)),
        "steps": steps,
        "errors": [str(item) for item in errors],
        "unresolved": [str(item) for item in unresolved],
        "expected_path_status": [item for item in expected_status if isinstance(item, dict)],
        "log_path": str(payload.get("smoke", {}).get("log_path", "")).strip()
        if isinstance(payload.get("smoke"), dict)
        else "",
    }


def _research_phase_label(state: dict) -> str:
    bootstrap = state.get("bootstrap")
    if isinstance(bootstrap, dict) and bootstrap:
        status = str(bootstrap.get("status", "")).strip()
        if status in {"pending", "resolved", "running"}:
            return "Prepare: Environment / Data / Smoke"
        if status == "failed":
            return "Prepare: Failed"
        if status == "unresolved":
            return "Prepare: Needs Bootstrap Overrides"

    graph = state.get("graph")
    if not graph:
        return PHASE_NAMES.get(state["phase"], "unknown")

    counts = graph.get("frontier_status_counts", {})
    if counts.get("draft"):
        return "Research Loop: Critic Preflight"
    if counts.get("needs_post_review"):
        return "Research Loop: Critic Post-Review"
    if counts.get("running"):
        return "Research Loop: Experiment Running"
    if counts.get("approved") or counts.get("needs_repro"):
        return "Research Loop: Experiment Queue Active"
    if graph.get("frontier_total", 0) > 0:
        return "Research Loop: Frontier Archived"
    return "Research Loop: Idle"


def parse_research_state(repo_path: Path) -> dict:
    """Parse .research/ directory into a state dict."""
    research = repo_path / ".research"
    state = {}

    config_error = None
    try:
        cfg = load_config(research, strict=True)
    except ValueError as exc:
        cfg = ResearchConfig()
        config_error = str(exc)
    state["mode"] = cfg.mode
    state["protocol"] = cfg.protocol
    state["protocol_supported"] = cfg.protocol == RESEARCH_PROTOCOL and config_error is None
    state["primary_metric"] = cfg.primary_metric
    state["direction"] = cfg.direction
    state["manager_batch_size"] = cfg.manager_batch_size
    state["config_error"] = config_error
    state["graph"] = _load_graph_state(research)
    state["bootstrap"] = _load_bootstrap_state(research)

    # Parse results
    results_path = research / "results.tsv"
    rows = []
    if results_path.exists():
        with results_path.open() as f:
            rows = list(csv.DictReader(f, delimiter="\t"))

    state["total"] = len(rows)
    state["keep"] = sum(1 for r in rows if r.get("status") == "keep")
    state["discard"] = sum(1 for r in rows if r.get("status") == "discard")
    state["crash"] = sum(1 for r in rows if r.get("status") == "crash")
    state["recent"] = rows[-5:] if rows else []

    # Compute metric values — skip rows with non-numeric or NaN metrics
    # Default to higher_is_better when direction is empty (consistent with results_cmd.py)
    higher = state["direction"] != "lower_is_better"
    keep_rows = [r for r in rows if r.get("status") == "keep"]
    values = []
    for r in keep_rows:
        v = _safe_float(r.get("metric_value", ""))
        if v is not None:
            values.append(v)
    if values:
        state["baseline_value"] = values[0]
        state["current_value"] = values[-1]
        state["best_value"] = max(values) if higher else min(values)
    else:
        state["baseline_value"] = None
        state["current_value"] = None
        state["best_value"] = None

    state["phase"] = _detect_phase(research)
    state["phase_label"] = _research_phase_label(state)

    # Git branch
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=5,
        )
        state["branch"] = result.stdout.strip() if result.returncode == 0 else "unknown"
    except (subprocess.TimeoutExpired, OSError):
        state["branch"] = "unknown"

    return state


PHASE_NAMES = {
    1: "Phase 1: Understand Project",
    2: "Phase 2: Research Related Work",
    3: "Phase 3: Design Evaluation",
    4: "Phase 4: Prepare Repository",
    5: "Phase 5: Establish Baseline",
    6: "Phase 6: Experiment Loop",
}

SPARK_CHARS = "\u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"


def _sparkline(values: list[float]) -> str:
    """Generate a Unicode sparkline from a list of values."""
    if not values:
        return ""
    lo, hi = min(values), max(values)
    if lo == hi:
        return SPARK_CHARS[4] * len(values)
    return "".join(
        SPARK_CHARS[min(int((v - lo) / (hi - lo) * 7), 7)]
        for v in values
    )


def print_status(repo_path: Path, sparkline: bool = False) -> None:
    """Print formatted research status to terminal."""
    research = repo_path / ".research"
    if not research.exists():
        print("[ERROR] No .research/ directory found. Run 'open-researcher init' first.")
        raise SystemExit(1)

    state = parse_research_state(repo_path)
    console = Console()

    lines = []
    lines.append(f"  Phase: {state.get('phase_label', PHASE_NAMES.get(state['phase'], 'unknown'))}")
    lines.append(f"  Branch: {state['branch']}")
    lines.append(f"  Mode: {state['mode']}")
    protocol = state.get("protocol", "")
    if protocol:
        protocol_suffix = "" if state.get("protocol_supported", True) else " (unsupported)"
        lines.append(f"  Protocol: {protocol}{protocol_suffix}")
    if state.get("config_error"):
        lines.append(f"  Config Error: {state['config_error']}")
    lines.append("")

    graph = state.get("graph")
    if graph:
        if graph.get("error"):
            lines.append(f"  Research Graph Error: {graph['error']}")
        else:
            counts = graph.get("frontier_status_counts", {})
            lines.append("  Research Graph:")
            lines.append(
                "    "
                f"Hypotheses: {graph['hypotheses']}  "
                f"Specs: {graph['experiment_specs']}  "
                f"Evidence: {graph['evidence']}  "
                f"Claims: {graph['claim_updates']}"
            )
            lines.append(
                "    "
                f"Frontier: {graph['frontier_total']} total  "
                f"Runnable: {graph['frontier_runnable']}  "
                f"Draft: {counts.get('draft', 0)}  "
                f"Post-review: {counts.get('needs_post_review', 0)}  "
                f"Needs repro: {counts.get('needs_repro', 0)}"
            )
        lines.append("")

    bootstrap = state.get("bootstrap")
    if bootstrap:
        if bootstrap.get("error"):
            lines.append(f"  Bootstrap Error: {bootstrap['error']}")
        else:
            lines.append("  Bootstrap:")
            lines.append(
                f"    Status: {bootstrap.get('status', 'unknown')}  "
                f"Working dir: {bootstrap.get('working_dir', '.')}  "
                f"Python: {bootstrap.get('python_executable', '') or 'unresolved'}"
            )
            step_bits = []
            for step_name in ("install", "data", "smoke"):
                step = bootstrap.get("steps", {}).get(step_name, {})
                step_bits.append(f"{step_name}={step.get('status', 'unknown')}")
            lines.append("    " + "  ".join(step_bits))
            if bootstrap.get("errors"):
                lines.append("    Errors:")
                for item in bootstrap["errors"][:3]:
                    lines.append(f"      - {item}")
            if bootstrap.get("unresolved"):
                lines.append("    Unresolved:")
                for item in bootstrap["unresolved"][:3]:
                    lines.append(f"      - {item}")
            expected_status = bootstrap.get("expected_path_status", [])
            missing_paths = [item.get("path", "") for item in expected_status if not item.get("exists")]
            if missing_paths:
                lines.append("    Missing expected paths:")
                for item in missing_paths[:3]:
                    lines.append(f"      - {item}")
            if bootstrap.get("log_path"):
                lines.append(f"    Log: {bootstrap['log_path']}")
        lines.append("")

    if state["total"] > 0:
        lines.append("  Experiments:")
        lines.append(
            f"    Total: {state['total']}  "
            f"✓ keep: {state['keep']}  "
            f"✗ discard: {state['discard']}  "
            f"💥 crash: {state['crash']}"
        )
        lines.append("")

        if state["primary_metric"]:
            lines.append(f"  Primary Metric: {state['primary_metric']}")
            if state["baseline_value"] is not None:
                lines.append(f"    Baseline:  {state['baseline_value']:.4f}")
                lines.append(f"    Current:  {state['current_value']:.4f}")
                lines.append(f"    Best:  {state['best_value']:.4f}")
            lines.append("")

        lines.append(f"  Recent {len(state['recent'])} experiments:")
        status_icons = {"keep": "✓", "discard": "✗", "crash": "💥"}
        for r in reversed(state["recent"]):
            icon = status_icons.get(r.get("status", ""), "?")
            val = _safe_float(r.get("metric_value", ""))
            val_str = f"{val:.4f}" if val is not None else r.get("metric_value", "N/A")
            lines.append(f"    {icon} {val_str}  {r.get('description', '')}")
    else:
        lines.append("  No experiments yet")

    panel = Panel(
        "\n".join(lines),
        title="Open Researcher",
        border_style="blue",
    )
    console.print(panel)

    # Show sparkline if requested
    if sparkline:
        # Collect metric values from keep-status experiments
        results_path = research / "results.tsv"
        keep_values: list[float] = []
        if results_path.exists():
            with results_path.open() as f:
                for r in csv.DictReader(f, delimiter="\t"):
                    if r.get("status") == "keep":
                        v = _safe_float(r.get("metric_value", ""))
                        if v is not None:
                            keep_values.append(v)
        if keep_values:
            console.print(f"  Trend: {_sparkline(keep_values)}")

    # Show agent activity if available
    activity_path = research / "activity.json"
    if activity_path.exists():
        from open_researcher.activity import ActivityMonitor

        monitor = ActivityMonitor(research)
        all_act = monitor.get_all()
        if all_act:
            act_lines = ["  Agent Activity:"]
            for key, act in all_act.items():
                a_status = act.get("status", "idle")
                detail = act.get("detail", "")
                act_lines.append(f"    {key}: [{a_status}] {detail}")
            console.print(Panel("\n".join(act_lines), title="Agents", border_style="green"))
