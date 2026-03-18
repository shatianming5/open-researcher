"""Parallel GPU experiment execution — WorkerPool and helpers.

Provides GPU detection, git-worktree isolation, and a thread-pool
that claims frontier items from ``ResearchState``, runs agent steps
inside isolated worktrees, and writes results back.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# GPU detection
# ---------------------------------------------------------------------------


def detect_gpus() -> list[dict]:
    """Query ``nvidia-smi`` and return a list of GPU info dicts.

    Each dict contains ``index`` (int), ``memory_total_mb`` (int),
    and ``memory_free_mb`` (int).  Returns an empty list when
    ``nvidia-smi`` is unavailable or fails.
    """
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,memory.total,memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    gpus: list[dict] = []
    for line in result.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        try:
            gpus.append(
                {
                    "index": int(parts[0]),
                    "memory_total_mb": int(parts[1]),
                    "memory_free_mb": int(parts[2]),
                }
            )
        except (ValueError, IndexError):
            continue
    return gpus


# ---------------------------------------------------------------------------
# Git worktree helpers
# ---------------------------------------------------------------------------


def create_worktree(repo_path: Path, worker_id: str) -> Path:
    """Create a git worktree at ``.worktrees/<worker_id>``.

    Also symlinks ``.research`` from the main repo into the worktree
    so all state files remain shared.

    Returns the worktree path.
    """
    repo_path = repo_path.resolve()
    worktrees_dir = repo_path / ".worktrees"
    worktrees_dir.mkdir(parents=True, exist_ok=True)
    wt_path = worktrees_dir / worker_id
    branch_name = f"v2-worker-{worker_id}"

    # Prune stale worktrees first
    subprocess.run(
        ["git", "worktree", "prune"],
        cwd=str(repo_path),
        capture_output=True,
        timeout=30,
    )

    # Remove previous worktree if it exists
    if wt_path.exists():
        cleanup_worktree(repo_path, worker_id)

    # Delete leftover branch
    subprocess.run(
        ["git", "branch", "-D", branch_name],
        cwd=str(repo_path),
        capture_output=True,
        timeout=30,
    )

    # Create worktree + branch
    result = subprocess.run(
        ["git", "worktree", "add", "-b", branch_name, str(wt_path), "HEAD"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"git worktree add failed: {detail}")

    # Symlink .research into the worktree
    research_dir = repo_path / ".research"
    wt_research = wt_path / ".research"
    if wt_research.is_symlink() or wt_research.is_file():
        wt_research.unlink()
    elif wt_research.is_dir():
        shutil.rmtree(wt_research)

    if research_dir.exists():
        os.symlink(str(research_dir), str(wt_research))

    logger.debug("Created worktree %s (branch %s)", wt_path, branch_name)
    return wt_path


def cleanup_worktree(repo_path: Path, worker_id: str) -> None:
    """Remove a worktree and its branch for *worker_id*."""
    repo_path = repo_path.resolve()
    wt_path = repo_path / ".worktrees" / worker_id
    branch_name = f"v2-worker-{worker_id}"

    # Remove symlink first so git worktree remove doesn't complain
    wt_research = wt_path / ".research"
    if wt_research.is_symlink() or wt_research.is_file():
        wt_research.unlink()
    elif wt_research.is_dir():
        shutil.rmtree(wt_research, ignore_errors=True)

    if wt_path.exists():
        result = subprocess.run(
            ["git", "worktree", "remove", "--force", str(wt_path)],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0 and wt_path.exists():
            shutil.rmtree(wt_path, ignore_errors=True)

    subprocess.run(
        ["git", "worktree", "prune"],
        cwd=str(repo_path),
        capture_output=True,
        timeout=30,
    )
    subprocess.run(
        ["git", "branch", "-D", branch_name],
        cwd=str(repo_path),
        capture_output=True,
        timeout=30,
    )
    logger.debug("Cleaned up worktree %s", wt_path)


# ---------------------------------------------------------------------------
# WorkerPool
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkerPool:
    """Thread-pool that claims frontier items and executes experiments.

    Parameters
    ----------
    repo_path:
        Repository root (used for worktree creation).
    state:
        ``ResearchState`` instance for graph / activity / result access.
    agent_factory:
        Callable returning a fresh agent object with a ``.run()`` method.
    skill_content:
        Skill content string passed to each agent invocation.
    max_workers:
        Hard cap on concurrent worker threads.
    gpu_mem_per_worker_mb:
        Memory budget per worker used to compute GPU slot assignments.
    on_output:
        Callback ``(str) -> None`` for streaming worker log lines.
    """

    def __init__(
        self,
        repo_path: Path,
        state: Any,
        agent_factory: Callable,
        skill_content: str,
        max_workers: int = 4,
        gpu_mem_per_worker_mb: int = 8192,
        on_output: Callable[[str], None] | None = None,
    ) -> None:
        self.repo_path = Path(repo_path).resolve()
        self.state = state
        self.agent_factory = agent_factory
        self.skill_content = skill_content
        self.max_workers = max(int(max_workers), 1)
        self.gpu_mem_per_worker_mb = max(int(gpu_mem_per_worker_mb), 0)
        self.on_output = on_output or (lambda _msg: None)

        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._claim_lock = threading.Lock()

    # -- frontier claiming --------------------------------------------------

    def claim_frontier(self, worker_id: str) -> dict | None:
        """Atomically claim the highest-priority approved frontier item.

        Sets ``status="running"`` and ``claimed_by=worker_id`` on the
        graph item.  Returns the item dict, or ``None`` if nothing is
        available.
        """
        with self._claim_lock:
            graph = self.state.load_graph()
            frontier = graph.get("frontier", [])

            # Find approved items sorted by priority (higher = first)
            candidates = [
                item for item in frontier
                if item.get("status") == "approved"
            ]
            if not candidates:
                return None

            candidates.sort(
                key=lambda it: (-(it.get("priority", 0)), it.get("id", "")),
            )
            chosen = candidates[0]
            chosen["status"] = "running"
            chosen["claimed_by"] = worker_id
            chosen["claimed_at"] = _now_iso()

            self.state.save_graph(graph)
            return dict(chosen)

    # -- result recording ---------------------------------------------------

    def finalize_experiment(
        self,
        worker_id: str,
        frontier_id: str,
        result: dict,
    ) -> None:
        """Mark a frontier item as ``needs_post_review`` and record the result."""
        # Update graph
        graph = self.state.load_graph()
        for item in graph.get("frontier", []):
            if item.get("id") == frontier_id:
                item["status"] = "needs_post_review"
                break
        self.state.save_graph(graph)

        # Append result row
        self.state.append_result(
            {
                "worker": worker_id,
                "frontier_id": frontier_id,
                "status": result.get("status", "done"),
                "metric": result.get("metric", ""),
                "value": str(result.get("value", "")),
                "description": result.get("description", ""),
            }
        )

        # Update worker activity
        self.state.update_worker(worker_id, status="idle", frontier_id="")

    # -- GPU slot resolution ------------------------------------------------

    def _resolve_gpu_assignments(self) -> list[dict]:
        """Compute worker slot assignments based on available GPU memory.

        Returns a list of ``{"worker_id": str, "gpu_index": int}`` dicts,
        one per slot.  Falls back to CPU-only slots when no GPUs are
        detected or the budget is zero.
        """
        if self.gpu_mem_per_worker_mb <= 0:
            return [
                {"worker_id": f"w{i}", "gpu_index": -1}
                for i in range(self.max_workers)
            ]

        gpus = detect_gpus()
        if not gpus:
            return [
                {"worker_id": f"w{i}", "gpu_index": -1}
                for i in range(self.max_workers)
            ]

        slots: list[dict] = []
        for gpu in gpus:
            free = gpu["memory_free_mb"]
            n_slots = free // self.gpu_mem_per_worker_mb
            for _ in range(n_slots):
                if len(slots) >= self.max_workers:
                    break
                slots.append(
                    {
                        "worker_id": f"w{len(slots)}",
                        "gpu_index": gpu["index"],
                    }
                )
            if len(slots) >= self.max_workers:
                break

        # Ensure at least one slot even if GPU memory is insufficient
        if not slots:
            slots.append({"worker_id": "w0", "gpu_index": gpus[0]["index"]})

        return slots

    # -- worker loop --------------------------------------------------------

    def _worker_loop(self, worker_id: str, gpu_index: int) -> None:
        """Claim→worktree→agent.run→finalize→repeat until stopped."""
        self.on_output(f"[{worker_id}] started (gpu={gpu_index})")
        self.state.update_worker(worker_id, status="idle", gpu=gpu_index)

        while not self._stop.is_set():
            # Pause check
            if self.state.is_paused():
                self.state.update_worker(worker_id, status="paused")
                self._stop.wait(2.0)
                continue

            # Claim next experiment
            item = self.claim_frontier(worker_id)
            if item is None:
                self.on_output(f"[{worker_id}] no work available, stopping")
                break

            frontier_id = item.get("id", "unknown")
            self.on_output(f"[{worker_id}] claimed {frontier_id}")
            self.state.update_worker(
                worker_id, status="running", frontier_id=frontier_id,
            )

            # Create worktree
            wt_path: Path | None = None
            try:
                wt_path = create_worktree(self.repo_path, worker_id)
            except Exception as exc:
                self.on_output(
                    f"[{worker_id}] worktree creation failed: {exc}"
                )
                self.finalize_experiment(
                    worker_id, frontier_id,
                    {"status": "error", "description": f"worktree failed: {exc}"},
                )
                continue

            # Run agent
            env_override = {}
            if gpu_index >= 0:
                env_override["CUDA_VISIBLE_DEVICES"] = str(gpu_index)

            result: dict = {"status": "error", "description": "unknown"}
            try:
                agent = self.agent_factory()
                result = agent.run(
                    work_dir=wt_path,
                    skill_content=self.skill_content,
                    frontier_item=item,
                    env=env_override,
                )
                if not isinstance(result, dict):
                    result = {"status": "done", "description": str(result)}
            except Exception as exc:
                self.on_output(f"[{worker_id}] agent error: {exc}")
                result = {"status": "error", "description": str(exc)}

            # Finalize
            self.finalize_experiment(worker_id, frontier_id, result)
            self.on_output(
                f"[{worker_id}] finished {frontier_id} "
                f"status={result.get('status', '?')}"
            )

            # Cleanup worktree
            if wt_path is not None:
                try:
                    cleanup_worktree(self.repo_path, worker_id)
                except Exception as exc:
                    self.on_output(
                        f"[{worker_id}] worktree cleanup failed: {exc}"
                    )

        self.state.update_worker(worker_id, status="stopped")
        self.on_output(f"[{worker_id}] stopped")

    # -- pool lifecycle -----------------------------------------------------

    def run(self) -> None:
        """Start all worker threads."""
        slots = self._resolve_gpu_assignments()
        self.on_output(
            f"[pool] starting {len(slots)} worker(s) "
            f"(max={self.max_workers})"
        )
        self.state.update_phase("running")

        for slot in slots:
            wid = slot["worker_id"]
            gpu = slot["gpu_index"]
            t = threading.Thread(
                target=self._worker_loop,
                args=(wid, gpu),
                name=f"worker-{wid}",
                daemon=True,
            )
            self._threads.append(t)
            t.start()

    def wait(self, timeout: float | None = None) -> None:
        """Join all worker threads with an optional *timeout* (seconds)."""
        deadline = (time.monotonic() + timeout) if timeout is not None else None
        for t in self._threads:
            if deadline is not None:
                remaining = max(deadline - time.monotonic(), 0)
                t.join(timeout=remaining)
            else:
                t.join()

    def stop(self) -> None:
        """Signal all workers to stop after their current iteration."""
        self._stop.set()
