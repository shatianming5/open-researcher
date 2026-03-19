"""Deterministic benchmark smoke runner for lightweight release-gate examples."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from open_researcher.bootstrap import run_bootstrap_prepare
from open_researcher.config import load_config, require_supported_protocol
from open_researcher.evaluation_contract import ensure_evaluation_contract
from open_researcher.graph_protocol import initialize_graph_runtime_state
from open_researcher.results_cmd import write_final_results_tsv
from open_researcher.storage import atomic_write_text

_METRIC_RE_TEMPLATE = r"(?<![A-Za-z0-9_]){metric}(?![A-Za-z0-9_])[\s:=]+(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"


def _load_bootstrap_state(research_dir: Path) -> dict:
    path = research_dir / "bootstrap_state.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _smoke_env(repo_path: Path, research_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    state = _load_bootstrap_state(research_dir)
    python_env = state.get("python_env", {}) if isinstance(state.get("python_env"), dict) else {}
    executable = Path(str(python_env.get("executable", "") or "").strip())
    bin_dir: Path | None = None
    if executable.is_file():
        bin_dir = executable.parent
    else:
        repo_venv_bin = repo_path / ".venv" / "bin"
        if repo_venv_bin.is_dir():
            bin_dir = repo_venv_bin
    if bin_dir is not None:
        env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["OPEN_RESEARCHER_EVAL_LOG"] = str(research_dir / "eval_output.log")
    env["OPEN_RESEARCHER_RESEARCH_DIR"] = str(research_dir)
    return env


def _extract_metric_value(output: str, metric_name: str) -> float:
    pattern = re.compile(_METRIC_RE_TEMPLATE.format(metric=re.escape(metric_name)))
    matches = pattern.findall(output)
    if not matches:
        raise ValueError(f"Could not find metric {metric_name!r} in smoke output.")
    return float(matches[-1])


def run_benchmark_smoke(repo_path: Path, *, description: str = "benchmark smoke baseline") -> dict[str, object]:
    """Run prepare + smoke for a benchmark repo and record one metric row."""
    research_dir = repo_path / ".research"
    if not research_dir.is_dir():
        raise FileNotFoundError(f"{research_dir} not found")

    cfg = load_config(research_dir, strict=True)
    require_supported_protocol(cfg)
    initialize_graph_runtime_state(research_dir, cfg)
    ensure_evaluation_contract(research_dir, cfg)

    prepare_code, _state = run_bootstrap_prepare(repo_path, research_dir, cfg)
    if prepare_code != 0:
        raise RuntimeError(f"Prepare failed with exit code {prepare_code}.")

    metric_name = str(cfg.primary_metric or "").strip()
    smoke_command = str(cfg.bootstrap_smoke_command or "").strip()
    if not metric_name:
        raise ValueError("config.yaml metrics.primary.name must be set for benchmark smoke.")
    if not smoke_command:
        raise ValueError("config.yaml bootstrap.smoke_command must be set for benchmark smoke.")

    env = _smoke_env(repo_path, research_dir)
    result = subprocess.run(
        ["/bin/zsh", "-lc", smoke_command],
        cwd=str(repo_path),
        env=env,
        capture_output=True,
        text=True,
    )
    combined_output = (result.stdout or "") + (result.stderr or "")
    atomic_write_text(research_dir / "eval_output.log", combined_output)
    if result.returncode != 0:
        raise RuntimeError(f"Smoke command failed with exit code {result.returncode}:\n{combined_output}")

    metric_value = _extract_metric_value(combined_output, metric_name)
    record_script = research_dir / "scripts" / "record.py"
    record_result = subprocess.run(
        [
            sys.executable,
            str(record_script),
            "--metric",
            metric_name,
            "--value",
            str(metric_value),
            "--status",
            "keep",
            "--desc",
            description,
        ],
        cwd=str(repo_path),
        env=env,
        capture_output=True,
        text=True,
    )
    if record_result.returncode != 0:
        raise RuntimeError(
            "Failed to record smoke result:\n"
            f"{record_result.stdout or ''}{record_result.stderr or ''}"
        )

    write_final_results_tsv(repo_path)
    return {
        "repo": str(repo_path),
        "metric_name": metric_name,
        "metric_value": metric_value,
        "smoke_command": smoke_command,
        "prepare_code": prepare_code,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic benchmark smoke for a repo.")
    parser.add_argument("repo", nargs="?", default=".", help="Benchmark repo path (default: current directory)")
    parser.add_argument("--desc", default="benchmark smoke baseline", help="Description to record in results.tsv")
    args = parser.parse_args()

    summary = run_benchmark_smoke(Path(args.repo).resolve(), description=args.desc)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
