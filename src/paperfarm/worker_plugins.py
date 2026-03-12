"""Optional worker runtime plugins for advanced parallel execution."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from paperfarm.failure_memory import (
    MEMORY_POLICY,
    FailureMemoryLedger,
    classify_failure,
)
from paperfarm.gpu_manager import GPUManager
from paperfarm.resource_scheduler import (
    normalize_resource_request,
    resolve_gpu_count,
    resolve_gpu_mem_mb,
    sort_pending_ideas,
)
from paperfarm.worktree import create_worktree, remove_worktree

logger = logging.getLogger(__name__)


class WorkspaceIsolationError(RuntimeError):
    """Raised when worker workspace isolation cannot be established."""


@dataclass(slots=True)
class GPUAllocation:
    """Concrete GPU allocation for one worker."""

    host: str | None = None
    device: int | None = None
    devices: list[dict] = field(default_factory=list)
    reservations: list[dict] = field(default_factory=list)
    resource_request: dict = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    log_lines: list[str] = field(default_factory=list)


class GPUAllocatorPlugin:
    """Optional GPU scheduling capability for worker execution."""

    def __init__(
        self,
        manager: GPUManager,
        *,
        default_memory_per_worker_mb: int = 4096,
        backfill_threshold_minutes: int = 30,
    ):
        self.manager = manager
        self.default_memory_per_worker_mb = max(int(default_memory_per_worker_mb or 0), 0)
        self.backfill_threshold_minutes = max(int(backfill_threshold_minutes or 0), 1)

    def worker_slots(self, max_workers: int) -> list[dict | None]:
        if max_workers <= 0:
            return []
        try:
            slots = self.manager.plan_slots(
                max_workers=max_workers,
                memory_mb=max(self.default_memory_per_worker_mb, 1),
            )
        except Exception:
            slots = []
        if isinstance(slots, list) and slots:
            return slots
        fallback = max(max_workers, 1)
        return [None] * max(fallback, 1)

    def describe_request(self, idea: dict) -> dict:
        request = normalize_resource_request(
            idea.get("resource_request"),
            default_gpu_mem_mb=self.default_memory_per_worker_mb,
            fallback_gpu_hint=idea.get("gpu_hint"),
        )
        try:
            status = self.manager.refresh()
        except Exception:
            status = []
        if not isinstance(status, list):
            status = []
        gpu_count = resolve_gpu_count(request, gpu_available=bool(status))
        request = dict(request)
        request["gpu_count"] = gpu_count
        request["gpu_mem_mb"] = resolve_gpu_mem_mb(
            request,
            default_gpu_mem_mb=self.default_memory_per_worker_mb,
            gpu_count=int(gpu_count or 0),
        )
        return request

    def _request_fits(self, request: dict, status: list[dict]) -> bool:
        requested_gpu_count = resolve_gpu_count(request, gpu_available=bool(status))
        if requested_gpu_count <= 0:
            return True
        requested_mem = max(
            resolve_gpu_mem_mb(
                request,
                default_gpu_mem_mb=self.default_memory_per_worker_mb,
                gpu_count=requested_gpu_count,
            ),
            1,
        )
        matched = 0
        for gpu in status:
            if self.manager.effective_free_mb(gpu) < requested_mem:
                continue
            reservations = gpu.get("reservations", [])
            has_existing = bool(reservations)
            if has_existing and not self.manager.allow_same_gpu_packing:
                continue
            if has_existing and bool(request.get("exclusive", False)):
                continue
            if has_existing and not bool(request.get("shareable", True)):
                continue
            matched += 1
            if matched >= requested_gpu_count:
                return True
        return False

    def select_claimable_idea(self, pending_ideas: list[dict]) -> str | None:
        if not pending_ideas:
            return None
        ordered = sort_pending_ideas(
            pending_ideas,
            default_gpu_mem_mb=self.default_memory_per_worker_mb,
            backfill_threshold_minutes=self.backfill_threshold_minutes,
        )
        try:
            status = self.manager.refresh()
        except Exception:
            status = []
        if not isinstance(status, list):
            status = []
        for idea in ordered:
            if self._request_fits(self.describe_request(idea), status):
                idea_id = str(idea.get("id", "")).strip()
                if idea_id:
                    return idea_id
        return None

    def allocate_for_idea(self, worker_id: str, idea: dict, preferred: dict | None = None) -> GPUAllocation | None:
        request = self.describe_request(idea)
        gpu_count = int(request.get("gpu_count", 0) or 0)
        if gpu_count <= 0:
            return GPUAllocation(resource_request=request)
        metadata = {
            "kind": "experiment",
            "task_kind": str(idea.get("workload_label", "")).strip(),
            "frontier_id": str(idea.get("frontier_id", "")).strip(),
            "execution_id": str(idea.get("execution_id", "")).strip(),
            "resource_profile": str(idea.get("resource_profile", "")).strip(),
            "workload_label": str(idea.get("workload_label", "")).strip(),
        }
        try:
            reservations = self.manager.reserve(worker_id, request, metadata=metadata, preferred=preferred)
        except Exception:
            logger.debug("GPU reservation failed", exc_info=True)
            return None
        if not isinstance(reservations, list):
            return None
        if reservations is None:
            return None
        visible_devices = ",".join(str(item.get("device")) for item in reservations)
        host = str(reservations[0].get("host", "local")).strip() if reservations else None
        device = int(reservations[0].get("device", 0)) if reservations else None
        reserved_mb = sum(int(item.get("memory_mb", 0) or 0) for item in reservations)

        return GPUAllocation(
            host=host,
            device=device,
            devices=[
                {"host": str(item.get("host", "local")).strip(), "device": int(item.get("device", 0))}
                for item in reservations
            ],
            reservations=reservations,
            resource_request=request,
            env={
                "CUDA_VISIBLE_DEVICES": visible_devices,
                "OPEN_RESEARCHER_GPU_MEMORY_BUDGET_MB": str(int(request.get("gpu_mem_mb", 0) or 0)),
                "OPEN_RESEARCHER_GPU_COUNT": str(int(request.get("gpu_count", 0) or 0)),
            },
            log_lines=[
                f"[{worker_id}] Reserved {len(reservations)} GPU(s) on {visible_devices or 'cpu'} "
                f"(budget {reserved_mb} MiB)"
            ],
        )

    def release(self, allocation: GPUAllocation) -> None:
        if not allocation.reservations:
            return
        try:
            self.manager.release_reservations(allocation.reservations)
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
            raise WorkspaceIsolationError(f"[{worker_id}] Worktree creation failed: {exc}") from exc

        def _cleanup() -> None:
            try:
                remove_worktree(self.repo_path, wt_path)
            except Exception as exc:
                raise WorkspaceIsolationError(f"[{worker_id}] Worktree cleanup failed: {exc}") from exc

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
    *,
    default_gpu_memory_mb: int = 4096,
) -> WorkerRuntimePlugins:
    """Build the default research-v1 worker runtime plugins."""
    return WorkerRuntimePlugins(
        gpu_allocator=GPUAllocatorPlugin(gpu_manager, default_memory_per_worker_mb=default_gpu_memory_mb)
        if gpu_manager is not None
        else None,
        failure_memory=FailureMemoryPlugin(FailureMemoryLedger(research_dir / "failure_memory_ledger.json")),
        workspace_isolation=WorktreeIsolationPlugin(repo_path),
    )


def build_legacy_worker_plugins(
    repo_path: Path,
    research_dir: Path,
    gpu_manager: GPUManager | None,
    *,
    default_gpu_memory_mb: int = 4096,
) -> WorkerRuntimePlugins:
    """Backward-compatible alias for the default worker runtime plugins."""
    return build_default_worker_plugins(
        repo_path=repo_path,
        research_dir=research_dir,
        gpu_manager=gpu_manager,
        default_gpu_memory_mb=default_gpu_memory_mb,
    )
