"""Helpers for research-v1 bootstrapping and compatibility projections."""

from __future__ import annotations

import shutil
import stat
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from open_researcher.bootstrap import ensure_bootstrap_state
from open_researcher.config import ResearchConfig
from open_researcher.research_graph import ResearchGraphStore
from open_researcher.research_memory import ResearchMemoryStore
from open_researcher.role_programs import ensure_internal_role_programs
from open_researcher.storage import atomic_write_json, atomic_write_text

_TEMPLATE_OUTPUTS: tuple[tuple[str, str], ...] = (
    ("config.yaml.j2", "config.yaml"),
    ("project-understanding.md.j2", "project-understanding.md"),
    ("evaluation.md.j2", "evaluation.md"),
    ("literature.md.j2", "literature.md"),
    ("ideas.md.j2", "ideas.md"),
    ("scout_program.md.j2", "scout_program.md"),
    ("research-strategy.md.j2", "research-strategy.md"),
)

_RESULTS_HEADER = "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
_FINAL_RESULTS_HEADER = (
    "timestamp\tcommit\tprimary_metric\tmetric_value\traw_status\tfinal_status\t"
    "evidence_reliability\tcritic_reason_code\tcritic_reason\tdescription\t"
    "frontier_id\texecution_id\n"
)
_DEFAULT_CONTROL = {
    "paused": False,
    "skip_current": False,
    "control_seq": 0,
    "applied_command_ids": [],
    "event_count": 0,
}


def _ensure_text_file(path: Path, content: str) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, content)


def _ensure_json_file(path: Path, payload: dict) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, payload)


def _ensure_runtime_scripts(research_dir: Path) -> None:
    scripts_dir = research_dir / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    scripts_src = Path(__file__).parent / "scripts"
    for script_name in ("record.py", "rollback.sh", "launch_detached.py"):
        src = scripts_src / script_name
        dst = scripts_dir / script_name
        if not dst.exists() or dst.read_bytes() != src.read_bytes():
            shutil.copy2(src, dst)
    rollback = scripts_dir / "rollback.sh"
    rollback.chmod(rollback.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def ensure_graph_protocol_artifacts(research_dir: Path) -> None:
    """Backfill research-v1 files for existing research directories."""
    research_dir.mkdir(parents=True, exist_ok=True)
    env = Environment(loader=PackageLoader("open_researcher", "templates"), autoescape=select_autoescape())
    context = {"tag": "", "goal": ""}
    for template_name, output_name in _TEMPLATE_OUTPUTS:
        path = research_dir / output_name
        if not path.exists():
            atomic_write_text(path, env.get_template(template_name).render(context))
    ensure_internal_role_programs(research_dir, env=env, context=context)

    _ensure_text_file(research_dir / "results.tsv", _RESULTS_HEADER)
    _ensure_text_file(research_dir / "final_results.tsv", _FINAL_RESULTS_HEADER)
    _ensure_json_file(research_dir / "idea_pool.json", {"ideas": []})
    _ensure_json_file(research_dir / "activity.json", {})
    _ensure_json_file(research_dir / "control.json", _DEFAULT_CONTROL)
    _ensure_text_file(research_dir / "events.jsonl", "")
    _ensure_json_file(research_dir / "experiment_progress.json", {"phase": "init"})
    _ensure_json_file(research_dir / "gpu_status.json", {"gpus": []})
    (research_dir / "worktrees").mkdir(exist_ok=True)
    _ensure_runtime_scripts(research_dir)

    ensure_bootstrap_state(research_dir / "bootstrap_state.json")
    ResearchGraphStore(research_dir / "research_graph.json").ensure_exists()
    ResearchMemoryStore(research_dir / "research_memory.json").ensure_exists()


def initialize_graph_runtime_state(research_dir: Path, cfg: ResearchConfig) -> dict:
    """Ensure research-v1 files exist and prime repo profile from config."""
    ensure_graph_protocol_artifacts(research_dir)
    store = ResearchGraphStore(research_dir / "research_graph.json")
    return store.update_repo_profile(
        primary_metric=cfg.primary_metric,
        direction=cfg.direction,
    )


def resolve_role_agent_name(cfg: ResearchConfig, role: str, fallback: str | None = None) -> str | None:
    """Resolve a role-specific agent override with primary-agent fallback."""
    role_value = cfg.role_agents.get(role) if isinstance(cfg.role_agents, dict) else None
    selected = str(role_value or fallback or "").strip()
    return selected or None
