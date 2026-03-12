"""Helpers for research-v1 bootstrapping and compatibility projections."""

from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, PackageLoader

from paperfarm.config import ResearchConfig
from paperfarm.research_graph import ResearchGraphStore
from paperfarm.research_memory import ResearchMemoryStore


def ensure_graph_protocol_artifacts(research_dir: Path) -> None:
    """Backfill research-v1 files for existing research directories."""
    env = Environment(loader=PackageLoader("paperfarm", "templates"))
    for template_name, output_name in [
        ("scout_program.md.j2", "scout_program.md"),
        ("manager_program.md.j2", "manager_program.md"),
        ("critic_program.md.j2", "critic_program.md"),
        ("experiment_program.md.j2", "experiment_program.md"),
    ]:
        output_path = research_dir / output_name
        if not output_path.exists():
            output_path.write_text(env.get_template(template_name).render({}))

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
