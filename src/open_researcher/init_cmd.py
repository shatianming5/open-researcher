"""Implementation of the 'init' command."""

import json
import shutil
import stat
import subprocess
import sys
from datetime import date
from pathlib import Path

from jinja2 import Environment, PackageLoader

from open_researcher.bootstrap import ensure_bootstrap_state
from open_researcher.research_graph import ResearchGraphStore
from open_researcher.research_memory import ResearchMemoryStore
from open_researcher.role_programs import ensure_internal_role_programs


def _git_info_exclude_path(repo_path: Path) -> Path | None:
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    git_dir = Path(result.stdout.strip())
    if not git_dir.is_absolute():
        git_dir = (repo_path / git_dir).resolve()
    return git_dir / "info" / "exclude"


def _ensure_git_exclude_patterns(repo_path: Path, patterns: list[str]) -> None:
    exclude_path = _git_info_exclude_path(repo_path)
    if exclude_path is None:
        return
    exclude_path.parent.mkdir(parents=True, exist_ok=True)
    existing_text = exclude_path.read_text(encoding="utf-8") if exclude_path.exists() else ""
    existing_lines = existing_text.splitlines()
    existing = {line.strip() for line in existing_lines if line.strip()}
    missing = [pattern for pattern in patterns if pattern not in existing]
    if not missing:
        return
    with exclude_path.open("a", encoding="utf-8") as f:
        if existing_text and not existing_text.endswith("\n"):
            f.write("\n")
        for pattern in missing:
            f.write(f"{pattern}\n")


def do_init(repo_path: Path, tag: str | None = None) -> None:
    """Initialize .research/ directory in the given repo."""
    git_dir = repo_path / ".git"
    if not git_dir.exists():
        print("[ERROR] Not a git repository. Run 'git init' first.", file=sys.stderr)
        raise SystemExit(1)

    research_dir = repo_path / ".research"

    if research_dir.exists():
        print(f"[ERROR] .research/ already exists at {research_dir}", file=sys.stderr)
        raise SystemExit(1)

    # Generate tag from date if not provided
    if tag is None:
        today = date.today()
        tag = today.strftime("%b%d").lower()  # e.g. "mar08"

    # Render templates
    env = Environment(loader=PackageLoader("open_researcher", "templates"))
    context = {"tag": tag, "goal": ""}

    research_dir.mkdir()

    # Render each template
    for template_name, output_name in [
        ("config.yaml.j2", "config.yaml"),
        ("project-understanding.md.j2", "project-understanding.md"),
        ("evaluation.md.j2", "evaluation.md"),
        ("literature.md.j2", "literature.md"),
        ("ideas.md.j2", "ideas.md"),
        ("scout_program.md.j2", "scout_program.md"),
        ("research-strategy.md.j2", "research-strategy.md"),
    ]:
        template = env.get_template(template_name)
        content = template.render(context)
        (research_dir / output_name).write_text(content)
    ensure_internal_role_programs(research_dir, env=env, context=context)

    # Create results.tsv with header
    header = "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
    (research_dir / "results.tsv").write_text(header)
    final_header = (
        "timestamp\tcommit\tprimary_metric\tmetric_value\traw_status\tfinal_status\t"
        "evidence_reliability\tcritic_reason_code\tcritic_reason\tdescription\t"
        "frontier_id\texecution_id\n"
    )
    (research_dir / "final_results.tsv").write_text(final_header)

    (research_dir / "idea_pool.json").write_text(json.dumps({"ideas": []}, indent=2))
    (research_dir / "activity.json").write_text("{}")
    (research_dir / "control.json").write_text(json.dumps({"paused": False, "skip_current": False}, indent=2))
    (research_dir / "events.jsonl").write_text("")
    (research_dir / "experiment_progress.json").write_text(json.dumps({"phase": "init"}, indent=2))
    ensure_bootstrap_state(research_dir / "bootstrap_state.json")
    ResearchGraphStore(research_dir / "research_graph.json").ensure_exists()
    ResearchMemoryStore(research_dir / "research_memory.json").ensure_exists()

    # Create GPU status file for parallel experiments
    (research_dir / "gpu_status.json").write_text(json.dumps({"gpus": []}, indent=2))

    # Keep the legacy directory for compatibility, but active worker worktrees
    # now live outside .research to avoid recursive shared-state symlinks.
    (research_dir / "worktrees").mkdir()

    # Copy helper scripts
    scripts_dir = research_dir / "scripts"
    scripts_dir.mkdir()

    scripts_src = Path(__file__).parent / "scripts"
    for script_name in ["record.py", "rollback.sh", "launch_detached.py"]:
        src = scripts_src / script_name
        dst = scripts_dir / script_name
        shutil.copy2(src, dst)

    # Make shell scripts executable
    rollback = scripts_dir / "rollback.sh"
    rollback.chmod(rollback.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    # .research is runtime state; keep it out of git history so parallel
    # worktrees can safely replace the directory with a shared symlink.
    _ensure_git_exclude_patterns(repo_path, ["/.research", "/.research/"])

    print(f"[OK] Initialized .research/ with tag '{tag}'")
    print(f"     Branch: research/{tag}")
    print("     Next: run `open-researcher run` to start the research-v1 loop")
