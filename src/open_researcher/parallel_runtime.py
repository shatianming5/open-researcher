"""Advanced parallel worker runtime for multi-GPU experiment execution."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from open_researcher.agents import get_agent
from open_researcher.config import ResearchConfig
from open_researcher.failure_memory import FailureMemoryLedger
from open_researcher.gpu_manager import GPUManager
from open_researcher.worker_plugins import (
    FailureMemoryPlugin,
    GPUAllocatorPlugin,
    WorkerRuntimePlugins,
    WorktreeIsolationPlugin,
)


@dataclass(slots=True)
class ParallelRuntimeProfile:
    """Explicit advanced runtime feature selection for parallel workers."""

    name: str
    gpu_allocation: bool
    failure_memory: bool
    worktree_isolation: bool


def resolve_parallel_worker_count(cfg: ResearchConfig) -> tuple[int, str | None]:
    """Resolve the effective worker count for the current runtime environment."""
    requested_raw = int(cfg.max_workers or 0)
    requested = max(requested_raw, 1)
    pinned_cuda = str(os.environ.get("CUDA_VISIBLE_DEVICES", "")).strip()
    if requested > 1 and pinned_cuda and not cfg.enable_gpu_allocation:
        reason = (
            "Externally pinned CUDA_VISIBLE_DEVICES without internal GPU allocation "
            "would run multiple workers on the same GPU; clamping to 1 worker to "
            "avoid confounded benchmark measurements."
        )
        return 1, reason
    return requested, None


def resolve_parallel_runtime_profile(cfg: ResearchConfig) -> ParallelRuntimeProfile:
    """Resolve which advanced runtime plugins are enabled for parallel execution."""
    worktree_isolation = bool(cfg.enable_worktree_isolation)
    if cfg.max_workers > 1:
        # Parallel experiments need isolated code workspaces even if the shared
        # .research state remains centralized.
        worktree_isolation = True
    enabled = [
        cfg.enable_gpu_allocation,
        cfg.enable_failure_memory,
        worktree_isolation,
    ]
    if all(enabled):
        name = "advanced"
    elif any(enabled):
        name = "custom"
    else:
        name = "minimal"
    return ParallelRuntimeProfile(
        name=name,
        gpu_allocation=cfg.enable_gpu_allocation,
        failure_memory=cfg.enable_failure_memory,
        worktree_isolation=worktree_isolation,
    )


def build_parallel_worker_plugins(
    repo_path: Path,
    research_dir: Path,
    cfg: ResearchConfig,
) -> tuple[ParallelRuntimeProfile, WorkerRuntimePlugins]:
    """Build the concrete worker plugin bundle for the chosen runtime profile."""
    profile = resolve_parallel_runtime_profile(cfg)
    gpu_manager = None
    if profile.gpu_allocation:
        gpu_manager = GPUManager(
            research_dir / "gpu_status.json",
            cfg.remote_hosts,
            allow_same_gpu_packing=cfg.gpu_allow_same_gpu_packing,
        )
    plugins = WorkerRuntimePlugins(
        gpu_allocator=GPUAllocatorPlugin(
            gpu_manager,
            default_memory_per_worker_mb=cfg.gpu_default_memory_per_worker_mb,
            backfill_threshold_minutes=cfg.scheduler_backfill_threshold_minutes,
        )
        if gpu_manager is not None
        else None,
        failure_memory=FailureMemoryPlugin(FailureMemoryLedger(research_dir / "failure_memory_ledger.json"))
        if profile.failure_memory
        else None,
        workspace_isolation=WorktreeIsolationPlugin(repo_path) if profile.worktree_isolation else None,
    )
    return profile, plugins


def estimate_parallel_frontier_target(research_dir: Path, cfg: ResearchConfig) -> int:
    """Estimate how many runnable frontier items to project for the current capacity."""
    requested_raw = int(cfg.max_workers or 0)
    requested, _reason = resolve_parallel_worker_count(cfg)
    if requested <= 0:
        requested = 1
    if not cfg.enable_gpu_allocation:
        return requested
    manager = GPUManager(
        research_dir / "gpu_status.json",
        cfg.remote_hosts,
        allow_same_gpu_packing=cfg.gpu_allow_same_gpu_packing,
    )
    allocator = GPUAllocatorPlugin(
        manager,
        default_memory_per_worker_mb=cfg.gpu_default_memory_per_worker_mb,
        backfill_threshold_minutes=cfg.scheduler_backfill_threshold_minutes,
    )
    slot_budget = (
        requested
        if requested_raw > 0
        else max(manager.estimate_packable_slots(default_memory_mb=cfg.gpu_default_memory_per_worker_mb), 1)
    )
    slots = allocator.worker_slots(slot_budget)
    return max(len(slots), 1)


def run_parallel_experiment_batch(
    repo_path: Path,
    research_dir: Path,
    cfg: ResearchConfig,
    exp_agent,
    on_output: Callable[[str], None],
    *,
    stop: threading.Event | None = None,
    max_claims: int | None = None,
    on_experiment_started: Callable[[dict], None] | None = None,
    on_experiment_finished: Callable[[dict], bool | None] | None = None,
) -> dict[str, int]:
    """Run one parallel batch against the current compatibility idea pool."""
    from open_researcher.idea_pool import IdeaPool
    from open_researcher.worker import WorkerManager

    idea_pool = IdeaPool(research_dir / "idea_pool.json")
    before = idea_pool.summary()
    profile, plugins = build_parallel_worker_plugins(repo_path, research_dir, cfg)
    requested_raw = int(cfg.max_workers or 0)
    effective_workers, clamp_reason = resolve_parallel_worker_count(cfg)
    if plugins.gpu_allocator is not None:
        slot_budget = (
            effective_workers
            if requested_raw > 0
            else max(
                estimate_parallel_frontier_target(research_dir, cfg),
                1,
            )
        )
        effective_workers = max(len(plugins.gpu_allocator.worker_slots(slot_budget)), 1)
    batch_started = 0
    batch_finished = 0
    failed_runs = 0

    def agent_factory():
        name = cfg.worker_agent or exp_agent.name
        return get_agent(name, config=cfg.agent_config.get(name))

    def _on_started(idea: dict) -> None:
        nonlocal batch_started
        batch_started += 1
        if on_experiment_started is not None:
            on_experiment_started(idea)

    def _on_finished(idea: dict) -> bool:
        nonlocal batch_finished, failed_runs
        batch_finished += 1
        if int(idea.get("exit_code", 0) or 0) != 0:
            failed_runs += 1
        if on_experiment_finished is not None:
            return bool(on_experiment_finished(idea))
        return False

    wm = WorkerManager(
        repo_path=repo_path,
        research_dir=research_dir,
        gpu_manager=None,
        idea_pool=idea_pool,
        agent_factory=agent_factory,
        max_workers=effective_workers,
        on_output=on_output,
        runtime_plugins=plugins,
        stop_event=stop,
        max_claims=max_claims,
        timeout_seconds=cfg.timeout,
        on_experiment_started=_on_started,
        on_experiment_finished=_on_finished,
        backfill_threshold_minutes=cfg.scheduler_backfill_threshold_minutes,
    )

    on_output(
        "[system] Parallel experiment batch "
        f"{profile.name} (gpu={profile.gpu_allocation}, "
        f"failure_memory={profile.failure_memory}, "
        f"worktree={profile.worktree_isolation})"
    )
    if clamp_reason is not None:
        on_output(f"[system] {clamp_reason}")

    if before.get("pending", 0) <= 0:
        return {"experiments_completed": 0, "exit_code": 0, "failed_runs": 0, "started_runs": 0}

    wm.start()
    wm.join()
    after = idea_pool.summary()
    fatal_errors = wm.fatal_errors
    running_after = int(after.get("running", 0) or 0)
    resource_deadlocks = int(wm.resource_deadlocks or 0)
    return {
        "experiments_completed": batch_finished,
        "exit_code": 1 if failed_runs > 0 or fatal_errors > 0 or running_after > 0 or resource_deadlocks > 0 else 0,
        "failed_runs": failed_runs,
        "started_runs": batch_started,
        "fatal_errors": fatal_errors,
        "running_after": running_after,
        "resource_deadlocks": resource_deadlocks,
        "stop_reason": "resource_deadlock" if resource_deadlocks > 0 else None,
    }
