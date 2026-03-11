"""Typed config reader for .research/config.yaml."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

RESEARCH_PROTOCOL = "research-v1"
PROTOCOL_ALIASES = {
    "": RESEARCH_PROTOCOL,
    "legacy": RESEARCH_PROTOCOL,
    "graph-v1": RESEARCH_PROTOCOL,
    RESEARCH_PROTOCOL: RESEARCH_PROTOCOL,
}


@dataclass
class ResearchConfig:
    mode: str = "autonomous"
    timeout: int = 600
    max_crashes: int = 3
    max_experiments: int = 0
    max_workers: int = 0
    worker_agent: str = ""
    primary_metric: str = ""
    direction: str = ""
    web_search: bool = True
    search_interval: int = 5
    remote_hosts: list = field(default_factory=list)
    enable_gpu_allocation: bool = True
    enable_failure_memory: bool = True
    enable_worktree_isolation: bool = True
    protocol: str = RESEARCH_PROTOCOL
    manager_batch_size: int = 3
    critic_repro_policy: str = "best_or_surprising"
    enable_ideation_memory: bool = True
    enable_experiment_memory: bool = True
    enable_repo_type_prior: bool = True
    environment_text: str = ""
    bootstrap_auto_prepare: bool = True
    bootstrap_working_dir: str = "."
    bootstrap_python: str = ""
    bootstrap_install_command: str = ""
    bootstrap_data_command: str = ""
    bootstrap_smoke_command: str = ""
    bootstrap_expected_paths: list[str] = field(default_factory=list)
    bootstrap_requires_gpu: bool = False
    role_agents: dict = field(default_factory=dict)
    agent_config: dict = field(default_factory=dict)


def _read_config_payload(research_dir: Path, *, strict: bool = False) -> dict[str, Any]:
    """Read config.yaml as a raw mapping, optionally failing on parse errors."""
    config_path = research_dir / "config.yaml"
    if not config_path.exists():
        return {}
    try:
        raw = yaml.safe_load(config_path.read_text()) or {}
    except (yaml.YAMLError, OSError) as exc:
        if strict:
            raise ValueError(f"Failed to parse {config_path}: {exc}") from exc
        return {}
    if not isinstance(raw, dict):
        if strict:
            raise ValueError(f"Expected {config_path} to contain a YAML mapping.")
        return {}
    return raw


def load_config(research_dir: Path, *, strict: bool = False) -> ResearchConfig:
    """Load and parse config.yaml into a typed dataclass."""
    raw = _read_config_payload(research_dir, strict=strict)
    exp = raw.get("experiment", {})
    metrics = raw.get("metrics", {}).get("primary", {})
    gpu = raw.get("gpu", {})
    research = raw.get("research", {})
    runtime = raw.get("runtime", {})
    roles = raw.get("roles", {})
    memory = raw.get("memory", {})
    bootstrap = raw.get("bootstrap", {})
    raw_protocol = str(research.get("protocol", RESEARCH_PROTOCOL) or RESEARCH_PROTOCOL).strip()
    protocol = PROTOCOL_ALIASES.get(raw_protocol, raw_protocol)
    return ResearchConfig(
        mode=raw.get("mode", "autonomous"),
        timeout=exp.get("timeout", 600),
        max_crashes=exp.get("max_consecutive_crashes", 3),
        max_experiments=exp.get("max_experiments", 0),
        max_workers=exp.get("max_parallel_workers", 0),
        worker_agent=exp.get("worker_agent", ""),
        primary_metric=metrics.get("name", ""),
        direction=metrics.get("direction", ""),
        web_search=research.get("web_search", True),
        search_interval=research.get("search_interval", 5),
        remote_hosts=gpu.get("remote_hosts", []),
        enable_gpu_allocation=runtime.get("gpu_allocation", True),
        enable_failure_memory=runtime.get("failure_memory", True),
        enable_worktree_isolation=runtime.get("worktree_isolation", True),
        protocol=protocol,
        manager_batch_size=max(int(research.get("manager_batch_size", 3) or 3), 1),
        critic_repro_policy=str(
            research.get("critic_repro_policy", "best_or_surprising") or "best_or_surprising"
        ),
        enable_ideation_memory=bool(memory.get("ideation", True)),
        enable_experiment_memory=bool(memory.get("experiment", True)),
        enable_repo_type_prior=bool(memory.get("repo_type_prior", True)),
        environment_text=str(raw.get("environment", "") or ""),
        bootstrap_auto_prepare=bool(bootstrap.get("auto_prepare", True)),
        bootstrap_working_dir=str(bootstrap.get("working_dir", ".") or "."),
        bootstrap_python=str(bootstrap.get("python", "") or ""),
        bootstrap_install_command=str(bootstrap.get("install_command", "") or ""),
        bootstrap_data_command=str(bootstrap.get("data_command", "") or ""),
        bootstrap_smoke_command=str(bootstrap.get("smoke_command", "") or ""),
        bootstrap_expected_paths=bootstrap.get("expected_paths", [])
        if isinstance(bootstrap.get("expected_paths", []), list)
        else [],
        bootstrap_requires_gpu=bool(bootstrap.get("requires_gpu", False)),
        role_agents=roles if isinstance(roles, dict) else {},
        agent_config=raw.get("agents", {}),
    )


def require_supported_protocol(cfg: ResearchConfig) -> None:
    """Reject unknown protocol values instead of silently coercing them."""
    if cfg.protocol != RESEARCH_PROTOCOL:
        raise ValueError(
            f"Unsupported research.protocol={cfg.protocol!r}. "
            f"Supported values: {RESEARCH_PROTOCOL!r} "
            "(aliases: 'legacy', 'graph-v1')."
        )
