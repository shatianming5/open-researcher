"""Optional worker runtime plugins for advanced parallel execution."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from open_researcher.failure_memory import (
    MEMORY_POLICY,
    FailureMemoryLedger,
    classify_failure,
)
from open_researcher.gpu_manager import GPUManager
from open_researcher.worktree import create_worktree, remove_worktree

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class GPUAllocation:
    """Concrete GPU allocation for one worker."""

    host: str | None = None
    device: int | None = None
    env: dict[str, str] = field(default_factory=dict)
    log_lines: list[str] = field(default_factory=list)


class GPUAllocatorPlugin:
    """Optional GPU scheduling capability for worker execution."""

    def __init__(self, manager: GPUManager):
        self.manager = manager

    def worker_slots(self, max_workers: int) -> list[dict | None]:
        try:
            gpus = self.manager.refresh()
        except Exception:
            gpus = []
        available = [gpu for gpu in gpus if gpu.get("allocated_to") is None]
        if available:
            limit = min(max_workers, len(available)) if max_workers > 0 else len(available)
            return available[: max(limit, 1)]
        fallback = min(max_workers, 1) if max_workers > 0 else 1
        return [None] * max(fallback, 1)

    def allocate(self, worker_id: str, gpu: dict | None) -> GPUAllocation:
        if gpu is None:
            return GPUAllocation()

        alloc_result = self.manager.allocate(tag=worker_id)
        if alloc_result is not None:
            host, device = alloc_result
        else:
            host, device = gpu["host"], gpu["device"]

        return GPUAllocation(
            host=host,
            device=device,
            env={"CUDA_VISIBLE_DEVICES": str(device)},
            log_lines=[f"[{worker_id}] Allocated GPU {host}:{device}"],
        )

    def release(self, allocation: GPUAllocation) -> None:
        if allocation.host is None or allocation.device is None:
            return
        try:
            self.manager.release(allocation.host, allocation.device)
        except Exception:
            logger.debug("GPU release failed", exc_info=True)


@dataclass(slots=True)
class FailureMemoryContext:
    """Failure-memory hints derived for one idea."""

    failure_class: str
    ranked_fix_actions: list[str]
    first_fix_action: str
    log_lines: list[str]


class FailureMemoryPlugin:
    """Optional historical failure-memory capability for worker execution."""

    def __init__(self, ledger: FailureMemoryLedger):
        self.ledger = ledger

    def prepare(self, idea_description: str, worker_id: str) -> FailureMemoryContext:
        failure_class = classify_failure(idea_description)
        ranked_fixes = self.ledger.rank_fixes(failure_class)
        ranked_fix_actions = [
            str(item.get("fix_action", "")).strip() for item in ranked_fixes if str(item.get("fix_action", "")).strip()
        ]
        first_fix_action = ranked_fix_actions[0] if ranked_fix_actions else "generate_new_plan"
        log_lines = [f"[{worker_id}] Memory policy {MEMORY_POLICY}: first remediation action {first_fix_action}"]
        return FailureMemoryContext(
            failure_class=failure_class,
            ranked_fix_actions=ranked_fix_actions[:3],
            first_fix_action=first_fix_action,
            log_lines=log_lines,
        )

    def record(self, context: FailureMemoryContext, run_code: int) -> None:
        self.ledger.record(
            failure_class=context.failure_class,
            fix_action=context.first_fix_action,
            verification_result="pass" if run_code == 0 else "fail",
            recovery_iterations=1 if run_code == 0 else 2,
        )


@dataclass(slots=True)
class WorkspaceLease:
    """Workspace allocation for one worker run."""

    workdir: Path
    cleanup: Callable[[], None]
    log_lines: list[str] = field(default_factory=list)


class WorktreeIsolationPlugin:
    """Optional isolated-worktree capability for worker execution."""

    def __init__(self, repo_path: Path):
        self.repo_path = repo_path

    def acquire(self, worker_id: str, idea_id: str) -> WorkspaceLease:
        try:
            wt_path = create_worktree(self.repo_path, f"{worker_id}-{idea_id}")
        except Exception as exc:
            return WorkspaceLease(
                workdir=self.repo_path,
                cleanup=lambda: None,
                log_lines=[f"[{worker_id}] Worktree creation failed ({exc}), running in main repo"],
            )

        def _cleanup() -> None:
            try:
                remove_worktree(self.repo_path, wt_path)
            except Exception:
                logger.debug("Worktree cleanup failed", exc_info=True)

        return WorkspaceLease(
            workdir=wt_path,
            cleanup=_cleanup,
            log_lines=[f"[{worker_id}] Worktree created: {wt_path.name}"],
        )


@dataclass(slots=True)
class WorkerRuntimePlugins:
    """Bundle of optional advanced runtime plugins used by WorkerManager."""

    gpu_allocator: GPUAllocatorPlugin | None = None
    failure_memory: FailureMemoryPlugin | None = None
    workspace_isolation: WorktreeIsolationPlugin | None = None


def build_default_worker_plugins(
    repo_path: Path,
    research_dir: Path,
    gpu_manager: GPUManager | None,
) -> WorkerRuntimePlugins:
    """Build the default research-v1 worker runtime plugins."""
    return WorkerRuntimePlugins(
        gpu_allocator=GPUAllocatorPlugin(gpu_manager) if gpu_manager is not None else None,
        failure_memory=FailureMemoryPlugin(FailureMemoryLedger(research_dir / "failure_memory_ledger.json")),
        workspace_isolation=WorktreeIsolationPlugin(repo_path),
    )


def build_legacy_worker_plugins(
    repo_path: Path,
    research_dir: Path,
    gpu_manager: GPUManager | None,
) -> WorkerRuntimePlugins:
    """Backward-compatible alias for the default worker runtime plugins."""
    return build_default_worker_plugins(
        repo_path=repo_path,
        research_dir=research_dir,
        gpu_manager=gpu_manager,
    )
