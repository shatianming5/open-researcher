"""Helpers for research-v1 bootstrapping and compatibility projections."""

from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, PackageLoader

from open_researcher.config import ResearchConfig
from open_researcher.research_graph import ResearchGraphStore
from open_researcher.research_memory import ResearchMemoryStore
from open_researcher.role_programs import ensure_internal_role_programs


def ensure_graph_protocol_artifacts(research_dir: Path) -> None:
    """Backfill research-v1 files for existing research directories."""
    env = Environment(loader=PackageLoader("open_researcher", "templates"))
    scout_path = research_dir / "scout_program.md"
    if not scout_path.exists():
        scout_path.write_text(env.get_template("scout_program.md.j2").render({}))
    ensure_internal_role_programs(research_dir, env=env)

    progress_path = research_dir / "experiment_progress.json"
    if not progress_path.exists():
        progress_path.write_text(json.dumps({"phase": "init"}, indent=2))

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
