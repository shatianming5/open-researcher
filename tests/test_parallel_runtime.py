"""Tests for explicit parallel runtime profiles and plugins."""

from open_researcher.config import ResearchConfig
from open_researcher.parallel_runtime import (
    build_parallel_worker_plugins,
    resolve_parallel_runtime_profile,
    resolve_parallel_worker_count,
    run_parallel_experiment_batch,
)
from open_researcher.worker_plugins import WorkerRuntimePlugins


def test_parallel_runtime_returns_stop_reason_for_resource_deadlock(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    research = repo / ".research"
    research.mkdir()
    (research / "idea_pool.json").write_text(
        '{"ideas":[{"id":"idea-001","description":"blocked","status":"pending","priority":1,"gpu_hint":1}]}',
        encoding="utf-8",
    )

    class NeverFitAllocator:
        default_memory_per_worker_mb = 4096

        def worker_slots(self, max_workers: int):
            return [None] * max_workers

        def select_claimable_idea(self, pending_ideas):
            return pending_ideas[0]["id"] if pending_ideas else None

        def allocate_for_idea(self, worker_id, idea, preferred=None):
            return None

    monkeypatch.setattr(
        "open_researcher.parallel_runtime.build_parallel_worker_plugins",
        lambda repo_path, research_dir, cfg: (
            resolve_parallel_runtime_profile(cfg),
            WorkerRuntimePlugins(gpu_allocator=NeverFitAllocator()),
        ),
    )
    monkeypatch.setattr(
        "open_researcher.parallel_runtime.get_agent",
        lambda name, config=None: None,
    )

    result = run_parallel_experiment_batch(
        repo_path=repo,
        research_dir=research,
        cfg=ResearchConfig(max_workers=1, enable_gpu_allocation=True),
        exp_agent=type("Agent", (), {"name": "codex"})(),
        on_output=lambda line: None,
    )

    assert result["resource_deadlocks"] == 1
    assert result["stop_reason"] == "resource_deadlock"
    assert result["exit_code"] == 1


def test_parallel_runtime_profile_advanced_by_default():
    profile = resolve_parallel_runtime_profile(ResearchConfig())
    assert profile.name == "advanced"
    assert profile.gpu_allocation is True
    assert profile.failure_memory is True
    assert profile.worktree_isolation is True


def test_parallel_runtime_profile_can_disable_all_plugins(tmp_path):
    cfg = ResearchConfig(
        enable_gpu_allocation=False,
        enable_failure_memory=False,
        enable_worktree_isolation=False,
    )
    profile, plugins = build_parallel_worker_plugins(tmp_path, tmp_path / ".research", cfg)

    assert profile.name == "minimal"
    assert plugins.gpu_allocator is None
    assert plugins.failure_memory is None
    assert plugins.workspace_isolation is None


def test_parallel_runtime_forces_worktree_isolation_when_workers_are_parallel():
    cfg = ResearchConfig(
        max_workers=4,
        enable_gpu_allocation=False,
        enable_failure_memory=False,
        enable_worktree_isolation=False,
    )
    profile = resolve_parallel_runtime_profile(cfg)
    assert profile.worktree_isolation is True


def test_parallel_runtime_clamps_workers_when_cuda_is_pinned(monkeypatch):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "3")
    cfg = ResearchConfig(
        max_workers=4,
        enable_gpu_allocation=False,
    )
    workers, reason = resolve_parallel_worker_count(cfg)
    assert workers == 1
    assert reason is not None


def test_parallel_runtime_keeps_requested_workers_without_pinned_cuda(monkeypatch):
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    cfg = ResearchConfig(
        max_workers=4,
        enable_gpu_allocation=False,
    )
    workers, reason = resolve_parallel_worker_count(cfg)
    assert workers == 4
    assert reason is None
