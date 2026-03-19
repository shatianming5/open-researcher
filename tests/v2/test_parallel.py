"""Tests for open_researcher_v2.parallel module."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from open_researcher_v2.parallel import (
    WorkerPool,
    cleanup_worktree,
    create_worktree,
    detect_gpus,
)
from open_researcher_v2.state import ResearchState, _default_graph


# ---------------------------------------------------------------------------
# TestGPUDetection
# ---------------------------------------------------------------------------


class TestGPUDetection:
    """Mock nvidia-smi success and failure scenarios."""

    def test_successful_detection(self):
        fake_output = (
            "0, 24576, 20000\n"
            "1, 24576, 18000\n"
        )
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = fake_output

        with patch("open_researcher_v2.parallel.subprocess.run", return_value=mock_result) as mock_run:
            gpus = detect_gpus()

        assert len(gpus) == 2
        assert gpus[0] == {"index": 0, "memory_total_mb": 24576, "memory_free_mb": 20000}
        assert gpus[1] == {"index": 1, "memory_total_mb": 24576, "memory_free_mb": 18000}

        mock_run.assert_called_once()
        args = mock_run.call_args
        assert "nvidia-smi" in args[0][0][0]

    def test_nvidia_smi_not_found(self):
        with patch(
            "open_researcher_v2.parallel.subprocess.run",
            side_effect=FileNotFoundError("nvidia-smi not found"),
        ):
            gpus = detect_gpus()
        assert gpus == []

    def test_nvidia_smi_nonzero_exit(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with patch("open_researcher_v2.parallel.subprocess.run", return_value=mock_result):
            gpus = detect_gpus()
        assert gpus == []

    def test_nvidia_smi_timeout(self):
        with patch(
            "open_researcher_v2.parallel.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="nvidia-smi", timeout=30),
        ):
            gpus = detect_gpus()
        assert gpus == []

    def test_malformed_output_skipped(self):
        fake_output = (
            "0, 24576, 20000\n"
            "bad line\n"
            "2, abc, 18000\n"
        )
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = fake_output

        with patch("open_researcher_v2.parallel.subprocess.run", return_value=mock_result):
            gpus = detect_gpus()
        assert len(gpus) == 1
        assert gpus[0]["index"] == 0

    def test_empty_output(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""

        with patch("open_researcher_v2.parallel.subprocess.run", return_value=mock_result):
            gpus = detect_gpus()
        assert gpus == []


# ---------------------------------------------------------------------------
# TestFrontierClaiming
# ---------------------------------------------------------------------------


class TestFrontierClaiming:
    """Test claim_frontier atomicity and priority ordering."""

    def _make_pool(self, state: ResearchState) -> WorkerPool:
        return WorkerPool(
            repo_path=state.dir.parent,
            state=state,
            agent_factory=lambda: MagicMock(),
            skill_content="",
            max_workers=4,
            gpu_mem_per_worker_mb=0,
        )

    def test_claim_highest_priority(self, tmp_path):
        rd = tmp_path / ".research"
        rd.mkdir()
        state = ResearchState(rd)

        graph = _default_graph()
        graph["frontier"] = [
            {"id": "f1", "status": "approved", "priority": 1},
            {"id": "f2", "status": "approved", "priority": 5},
            {"id": "f3", "status": "approved", "priority": 3},
        ]
        state.save_graph(graph)

        pool = self._make_pool(state)
        item = pool.claim_frontier("w0")

        assert item is not None
        assert item["id"] == "f2"
        assert item["status"] == "running"
        assert item["claimed_by"] == "w0"

        # Verify graph was updated
        updated = state.load_graph()
        f2 = next(f for f in updated["frontier"] if f["id"] == "f2")
        assert f2["status"] == "running"
        assert f2["claimed_by"] == "w0"

    def test_skip_already_claimed(self, tmp_path):
        rd = tmp_path / ".research"
        rd.mkdir()
        state = ResearchState(rd)

        graph = _default_graph()
        graph["frontier"] = [
            {"id": "f1", "status": "running", "priority": 10, "claimed_by": "w0"},
            {"id": "f2", "status": "approved", "priority": 1},
        ]
        state.save_graph(graph)

        pool = self._make_pool(state)
        item = pool.claim_frontier("w1")

        assert item is not None
        assert item["id"] == "f2"

    def test_return_none_when_empty(self, tmp_path):
        rd = tmp_path / ".research"
        rd.mkdir()
        state = ResearchState(rd)

        graph = _default_graph()
        graph["frontier"] = []
        state.save_graph(graph)

        pool = self._make_pool(state)
        assert pool.claim_frontier("w0") is None

    def test_return_none_when_all_claimed(self, tmp_path):
        rd = tmp_path / ".research"
        rd.mkdir()
        state = ResearchState(rd)

        graph = _default_graph()
        graph["frontier"] = [
            {"id": "f1", "status": "running", "priority": 5, "claimed_by": "w0"},
            {"id": "f2", "status": "needs_post_review", "priority": 3},
        ]
        state.save_graph(graph)

        pool = self._make_pool(state)
        assert pool.claim_frontier("w1") is None

    def test_successive_claims_exhaust_frontier(self, tmp_path):
        rd = tmp_path / ".research"
        rd.mkdir()
        state = ResearchState(rd)

        graph = _default_graph()
        graph["frontier"] = [
            {"id": "f1", "status": "approved", "priority": 2},
            {"id": "f2", "status": "approved", "priority": 1},
        ]
        state.save_graph(graph)

        pool = self._make_pool(state)
        first = pool.claim_frontier("w0")
        assert first is not None
        assert first["id"] == "f1"

        second = pool.claim_frontier("w1")
        assert second is not None
        assert second["id"] == "f2"

        third = pool.claim_frontier("w2")
        assert third is None

    def test_priority_tiebreak_by_id(self, tmp_path):
        rd = tmp_path / ".research"
        rd.mkdir()
        state = ResearchState(rd)

        graph = _default_graph()
        graph["frontier"] = [
            {"id": "f-beta", "status": "approved", "priority": 5},
            {"id": "f-alpha", "status": "approved", "priority": 5},
        ]
        state.save_graph(graph)

        pool = self._make_pool(state)
        item = pool.claim_frontier("w0")
        assert item is not None
        # Alphabetically first id wins on tiebreak
        assert item["id"] == "f-alpha"


# ---------------------------------------------------------------------------
# TestFinalize
# ---------------------------------------------------------------------------


class TestFinalize:
    """Test finalize_experiment updates graph + results."""

    def test_finalize_updates_status_and_appends_result(self, tmp_path):
        rd = tmp_path / ".research"
        rd.mkdir()
        state = ResearchState(rd)

        graph = _default_graph()
        graph["frontier"] = [
            {"id": "f1", "status": "running", "claimed_by": "w0"},
        ]
        state.save_graph(graph)

        pool = WorkerPool(
            repo_path=tmp_path,
            state=state,
            agent_factory=lambda: MagicMock(),
            skill_content="",
        )
        pool.finalize_experiment(
            "w0", "f1",
            {"status": "keep", "metric": "accuracy", "value": "0.95"},
        )

        # Graph updated
        updated = state.load_graph()
        f1 = next(f for f in updated["frontier"] if f["id"] == "f1")
        assert f1["status"] == "needs_post_review"

        # Result appended
        results = state.load_results()
        assert len(results) == 1
        assert results[0]["worker"] == "w0"
        assert results[0]["value"] == "0.95"

        # Worker status updated
        act = state.load_activity()
        w = next(w for w in act["workers"] if w["id"] == "w0")
        assert w["status"] == "idle"


# ---------------------------------------------------------------------------
# TestGPUAssignments
# ---------------------------------------------------------------------------


class TestGPUAssignments:
    """Test _resolve_gpu_assignments with mocked GPU detection."""

    def test_cpu_fallback_when_budget_zero(self, tmp_path):
        rd = tmp_path / ".research"
        rd.mkdir()
        state = ResearchState(rd)
        pool = WorkerPool(
            repo_path=tmp_path,
            state=state,
            agent_factory=lambda: MagicMock(),
            skill_content="",
            max_workers=3,
            gpu_mem_per_worker_mb=0,
        )
        slots = pool._resolve_gpu_assignments()
        assert len(slots) == 3
        assert all(s["gpu_index"] == -1 for s in slots)

    def test_gpu_packing(self, tmp_path):
        rd = tmp_path / ".research"
        rd.mkdir()
        state = ResearchState(rd)
        pool = WorkerPool(
            repo_path=tmp_path,
            state=state,
            agent_factory=lambda: MagicMock(),
            skill_content="",
            max_workers=5,
            gpu_mem_per_worker_mb=8000,
        )
        with patch(
            "open_researcher_v2.parallel.detect_gpus",
            return_value=[
                {"index": 0, "memory_total_mb": 24000, "memory_free_mb": 24000},
                {"index": 1, "memory_total_mb": 24000, "memory_free_mb": 16000},
            ],
        ):
            slots = pool._resolve_gpu_assignments()

        # GPU 0: 24000 // 8000 = 3 slots, GPU 1: 16000 // 8000 = 2 slots -> 5 total
        assert len(slots) == 5
        gpu0_slots = [s for s in slots if s["gpu_index"] == 0]
        gpu1_slots = [s for s in slots if s["gpu_index"] == 1]
        assert len(gpu0_slots) == 3
        assert len(gpu1_slots) == 2

    def test_gpu_respects_max_workers(self, tmp_path):
        rd = tmp_path / ".research"
        rd.mkdir()
        state = ResearchState(rd)
        pool = WorkerPool(
            repo_path=tmp_path,
            state=state,
            agent_factory=lambda: MagicMock(),
            skill_content="",
            max_workers=2,
            gpu_mem_per_worker_mb=8000,
        )
        with patch(
            "open_researcher_v2.parallel.detect_gpus",
            return_value=[
                {"index": 0, "memory_total_mb": 48000, "memory_free_mb": 48000},
            ],
        ):
            slots = pool._resolve_gpu_assignments()

        assert len(slots) == 2

    def test_fallback_when_no_gpus(self, tmp_path):
        rd = tmp_path / ".research"
        rd.mkdir()
        state = ResearchState(rd)
        pool = WorkerPool(
            repo_path=tmp_path,
            state=state,
            agent_factory=lambda: MagicMock(),
            skill_content="",
            max_workers=2,
            gpu_mem_per_worker_mb=8000,
        )
        with patch("open_researcher_v2.parallel.detect_gpus", return_value=[]):
            slots = pool._resolve_gpu_assignments()

        assert len(slots) == 2
        assert all(s["gpu_index"] == -1 for s in slots)

    def test_at_least_one_slot_even_low_memory(self, tmp_path):
        rd = tmp_path / ".research"
        rd.mkdir()
        state = ResearchState(rd)
        pool = WorkerPool(
            repo_path=tmp_path,
            state=state,
            agent_factory=lambda: MagicMock(),
            skill_content="",
            max_workers=4,
            gpu_mem_per_worker_mb=50000,
        )
        with patch(
            "open_researcher_v2.parallel.detect_gpus",
            return_value=[
                {"index": 0, "memory_total_mb": 24000, "memory_free_mb": 24000},
            ],
        ):
            slots = pool._resolve_gpu_assignments()

        assert len(slots) >= 1
        assert slots[0]["gpu_index"] == 0


# ---------------------------------------------------------------------------
# TestWorktree
# ---------------------------------------------------------------------------


class TestWorktree:
    """Create and cleanup worktrees in a temporary git repo."""

    @pytest.fixture()
    def git_repo(self, tmp_path):
        """Initialise a minimal git repo with one commit."""
        subprocess.run(
            ["git", "init", str(tmp_path)],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(tmp_path), "config", "user.email", "test@test.com"],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(tmp_path), "config", "user.name", "Test"],
            capture_output=True,
            check=True,
        )
        readme = tmp_path / "README.md"
        readme.write_text("# Test\n")
        subprocess.run(
            ["git", "-C", str(tmp_path), "add", "."],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(tmp_path), "commit", "-m", "init"],
            capture_output=True,
            check=True,
        )
        return tmp_path

    def test_create_and_cleanup(self, git_repo):
        """Worktree is created on disk and removed cleanly."""
        wt = create_worktree(git_repo, "test-w0")
        assert wt.exists()
        assert (wt / "README.md").exists()
        assert wt.name == "test-w0"

        cleanup_worktree(git_repo, "test-w0")
        assert not wt.exists()

    def test_research_symlink(self, git_repo):
        """The .research directory is symlinked into the worktree."""
        research = git_repo / ".research"
        research.mkdir()
        (research / "config.yaml").write_text("test: true\n")

        wt = create_worktree(git_repo, "test-w1")
        wt_research = wt / ".research"
        assert wt_research.is_symlink()
        assert (wt_research / "config.yaml").read_text() == "test: true\n"

        cleanup_worktree(git_repo, "test-w1")

    def test_create_twice_replaces(self, git_repo):
        """Creating a worktree with the same id replaces the previous one."""
        wt1 = create_worktree(git_repo, "test-dup")
        assert wt1.exists()

        wt2 = create_worktree(git_repo, "test-dup")
        assert wt2.exists()
        assert wt1 == wt2  # same path

        cleanup_worktree(git_repo, "test-dup")
        assert not wt2.exists()

    def test_cleanup_nonexistent_is_safe(self, git_repo):
        """Cleaning up a non-existent worktree should not raise."""
        # Should not raise
        cleanup_worktree(git_repo, "never-created")


# ---------------------------------------------------------------------------
# TestWorkerPoolLifecycle
# ---------------------------------------------------------------------------


class TestWorkerPoolLifecycle:
    """Test run / stop / wait lifecycle."""

    def test_run_and_stop(self, tmp_path):
        """Pool starts, claims one item, and stops."""
        rd = tmp_path / ".research"
        rd.mkdir()
        state = ResearchState(rd)

        graph = _default_graph()
        graph["frontier"] = [
            {"id": "f1", "status": "approved", "priority": 1},
        ]
        state.save_graph(graph)

        output_lines: list[str] = []

        mock_agent = MagicMock()
        mock_agent.run.return_value = 0  # agent.run() returns int exit code

        pool = WorkerPool(
            repo_path=tmp_path,
            state=state,
            agent_factory=lambda: mock_agent,
            skill_content="test skill",
            max_workers=1,
            gpu_mem_per_worker_mb=0,
            on_output=output_lines.append,
        )

        # Patch worktree ops to avoid needing a real git repo
        with patch("open_researcher_v2.parallel.create_worktree", return_value=tmp_path):
            with patch("open_researcher_v2.parallel.cleanup_worktree"):
                pool.run()
                pool.wait(timeout=10.0)

        # Verify frontier was claimed and finalized
        final_graph = state.load_graph()
        f1 = next(f for f in final_graph["frontier"] if f["id"] == "f1")
        assert f1["status"] == "needs_post_review"

        results = state.load_results()
        assert len(results) == 1
        assert results[0]["status"] == "keep"

    def test_agent_receives_assigned_experiment(self, tmp_path):
        """Worker injects '## Assigned Experiment' section into program_content."""
        rd = tmp_path / ".research"
        rd.mkdir()
        state = ResearchState(rd)

        graph = _default_graph()
        graph["frontier"] = [
            {"id": "f1", "status": "approved", "priority": 3,
             "description": "Test experiment"},
        ]
        state.save_graph(graph)

        mock_agent = MagicMock()
        mock_agent.run.return_value = 0

        received_content = {}

        def _capture_run(wt_path, program_content="", **kwargs):
            received_content["content"] = program_content
            return 0

        mock_agent.run.side_effect = _capture_run

        pool = WorkerPool(
            repo_path=tmp_path,
            state=state,
            agent_factory=lambda: mock_agent,
            skill_content="base skill content",
            max_workers=1,
            gpu_mem_per_worker_mb=0,
        )

        with patch("open_researcher_v2.parallel.create_worktree", return_value=tmp_path):
            with patch("open_researcher_v2.parallel.cleanup_worktree"):
                pool.run()
                pool.wait(timeout=10.0)

        assert "content" in received_content
        content = received_content["content"]
        assert "## Assigned Experiment" in content
        assert "f1" in content
        assert "base skill content" in content
        assert "Do NOT claim a new item" in content

    def test_stop_signal(self, tmp_path):
        """Pool.stop() terminates workers."""
        rd = tmp_path / ".research"
        rd.mkdir()
        state = ResearchState(rd)

        # Infinite supply of frontier items
        counter = {"n": 0}
        original_load = state.load_graph

        def _rigged_load():
            g = original_load()
            counter["n"] += 1
            g["frontier"] = [
                {"id": f"f{counter['n']}", "status": "approved", "priority": 1}
            ]
            return g

        state.load_graph = _rigged_load

        mock_agent = MagicMock()
        mock_agent.run.return_value = 0  # agent.run() returns int exit code

        pool = WorkerPool(
            repo_path=tmp_path,
            state=state,
            agent_factory=lambda: mock_agent,
            skill_content="",
            max_workers=1,
            gpu_mem_per_worker_mb=0,
        )

        with patch("open_researcher_v2.parallel.create_worktree", return_value=tmp_path):
            with patch("open_researcher_v2.parallel.cleanup_worktree"):
                pool.run()
                # Let it run briefly
                import time
                time.sleep(0.3)
                pool.stop()
                pool.wait(timeout=5.0)

        # Should have processed at least one item
        results = state.load_results()
        assert len(results) >= 1
