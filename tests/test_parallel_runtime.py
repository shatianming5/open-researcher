"""Tests for explicit parallel runtime profiles and plugins."""

from open_researcher.config import ResearchConfig
from open_researcher.parallel_runtime import (
    build_parallel_worker_plugins,
    resolve_parallel_runtime_profile,
    resolve_parallel_worker_count,
)


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
