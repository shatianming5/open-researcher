"""Role program file helpers for research-v1 runtime internals."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from jinja2 import Environment, PackageLoader

RoleProgram = Literal["manager", "critic", "experiment"]

_ROLE_PROGRAM_SPECS: dict[RoleProgram, dict[str, str]] = {
    "manager": {
        "template": "manager_program.md.j2",
        "legacy": "manager_program.md",
        "internal": ".internal/role_programs/manager.md",
    },
    "critic": {
        "template": "critic_program.md.j2",
        "legacy": "critic_program.md",
        "internal": ".internal/role_programs/critic.md",
    },
    "experiment": {
        "template": "experiment_program.md.j2",
        "legacy": "experiment_program.md",
        "internal": ".internal/role_programs/experiment.md",
    },
}


def _template_env() -> Environment:
    return Environment(loader=PackageLoader("open_researcher", "templates"))


def legacy_role_program_file(role: RoleProgram) -> str:
    """Return legacy top-level role program filename."""
    return _ROLE_PROGRAM_SPECS[role]["legacy"]


def internal_role_program_file(role: RoleProgram) -> str:
    """Return internal role program path under .research/."""
    return _ROLE_PROGRAM_SPECS[role]["internal"]


def resolve_role_program_file(research_dir: Path, role: RoleProgram) -> str:
    """Pick internal role program path, with legacy fallback for compatibility."""
    internal_rel = internal_role_program_file(role)
    if (research_dir / internal_rel).exists():
        return internal_rel
    legacy_rel = legacy_role_program_file(role)
    if (research_dir / legacy_rel).exists():
        return legacy_rel
    return internal_rel


def ensure_internal_role_programs(
    research_dir: Path,
    *,
    env: Environment | None = None,
    context: dict | None = None,
) -> None:
    """Ensure internal role program files exist, migrating from legacy files when present."""
    template_env = env or _template_env()
    render_context = context or {}
    for role, spec in _ROLE_PROGRAM_SPECS.items():
        internal_path = research_dir / spec["internal"]
        if internal_path.exists():
            continue
        internal_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_path = research_dir / spec["legacy"]
        if legacy_path.exists():
            content = legacy_path.read_text(encoding="utf-8")
        else:
            content = template_env.get_template(spec["template"]).render(render_context)
        internal_path.write_text(content, encoding="utf-8")


def missing_role_programs(research_dir: Path) -> list[RoleProgram]:
    """Return roles missing both internal and legacy program files."""
    missing: list[RoleProgram] = []
    for role in _ROLE_PROGRAM_SPECS:
        internal_path = research_dir / internal_role_program_file(role)
        legacy_path = research_dir / legacy_role_program_file(role)
        if not internal_path.exists() and not legacy_path.exists():
            missing.append(role)
    return missing
