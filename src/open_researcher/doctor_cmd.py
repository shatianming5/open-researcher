"""Health check command for the research environment."""

import json
import shutil
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table


def run_doctor(repo_path: Path) -> list[dict]:
    """Run health checks. Returns list of {check, status, detail}."""
    results: list[dict] = []
    research = repo_path / ".research"

    # 1. Git repository
    git_dir = repo_path / ".git"
    if git_dir.exists():
        results.append({"check": "Git repository", "status": "OK", "detail": str(git_dir)})
    else:
        results.append({"check": "Git repository", "status": "FAIL", "detail": ".git not found"})

    # 2. .research/ directory
    if research.is_dir():
        results.append({"check": ".research/ directory", "status": "OK", "detail": str(research)})
    else:
        results.append({"check": ".research/ directory", "status": "FAIL", "detail": ".research/ not found"})

    # 3. config.yaml parseable
    config_path = research / "config.yaml"
    if config_path.exists():
        try:
            import yaml

            yaml.safe_load(config_path.read_text())
            results.append({"check": "config.yaml", "status": "OK", "detail": "Parseable"})
        except Exception as exc:
            results.append({"check": "config.yaml", "status": "FAIL", "detail": f"Parse error: {exc}"})
    else:
        results.append({"check": "config.yaml", "status": "WARN", "detail": "File not found"})

    # 4. results.tsv exists
    results_path = research / "results.tsv"
    if results_path.exists():
        results.append({"check": "results.tsv", "status": "OK", "detail": "Exists"})
    else:
        results.append({"check": "results.tsv", "status": "WARN", "detail": "File not found"})

    # 5. idea_pool.json parseable
    pool_path = research / "idea_pool.json"
    if pool_path.exists():
        try:
            data = json.loads(pool_path.read_text())
            count = len(data.get("ideas", []))
            results.append({"check": "idea_pool.json", "status": "OK", "detail": f"{count} ideas"})
        except (json.JSONDecodeError, OSError) as exc:
            results.append({"check": "idea_pool.json", "status": "FAIL", "detail": f"Parse error: {exc}"})
    else:
        results.append({"check": "idea_pool.json", "status": "WARN", "detail": "File not found"})

    # 6. activity.json parseable
    activity_path = research / "activity.json"
    if activity_path.exists():
        try:
            json.loads(activity_path.read_text())
            results.append({"check": "activity.json", "status": "OK", "detail": "Parseable"})
        except (json.JSONDecodeError, OSError) as exc:
            results.append({"check": "activity.json", "status": "FAIL", "detail": f"Parse error: {exc}"})
    else:
        results.append({"check": "activity.json", "status": "WARN", "detail": "File not found"})

    # 7. Agent binaries on PATH
    agents = ["claude", "codex", "aider", "opencode"]
    found = [a for a in agents if shutil.which(a)]
    missing = [a for a in agents if not shutil.which(a)]
    if found:
        detail = f"Found: {', '.join(found)}"
        if missing:
            detail += f"; Missing: {', '.join(missing)}"
        status = "OK" if not missing else "WARN"
        results.append({"check": "Agent binaries", "status": status, "detail": detail})
    else:
        results.append({"check": "Agent binaries", "status": "WARN", "detail": "No agents found on PATH"})

    # 8. Python >= 3.10
    major, minor = sys.version_info[:2]
    if (major, minor) >= (3, 10):
        results.append({"check": "Python >= 3.10", "status": "OK", "detail": f"{major}.{minor}"})
    else:
        results.append(
            {"check": "Python >= 3.10", "status": "FAIL", "detail": f"{major}.{minor} (need >= 3.10)"}
        )

    return results


def print_doctor(repo_path: Path) -> None:
    """Print doctor results as a Rich table."""
    checks = run_doctor(repo_path)
    console = Console()
    table = Table(title="Research Environment Health Check")
    table.add_column("Check", style="bold")
    table.add_column("Status")
    table.add_column("Detail")

    status_style = {
        "OK": "[green][OK][/green]",
        "WARN": "[yellow][WARN][/yellow]",
        "FAIL": "[red][FAIL][/red]",
    }

    for check in checks:
        table.add_row(
            check["check"],
            status_style.get(check["status"], check["status"]),
            check["detail"],
        )

    console.print(table)
