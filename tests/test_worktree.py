"""Tests for git worktree isolation module."""

import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from open_researcher.idea_pool import IdeaPool
from open_researcher.storage import atomic_write_json
from open_researcher.worktree import create_worktree, remove_worktree
from open_researcher.worktree import worktrees_root


def _init_git_repo(path: Path) -> None:
    """Initialize a minimal git repo with one commit."""
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(path), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(path), capture_output=True, check=True,
    )
    # Create a file and commit
    (path / "hello.py").write_text("print('hello')\n")
    subprocess.run(["git", "add", "."], cwd=str(path), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=str(path), capture_output=True, check=True,
    )


def _setup_research(path: Path) -> Path:
    """Create .research/ directory with test files."""
    research = path / ".research"
    research.mkdir()
    (research / "experiment_program.md").write_text("Run experiment")
    (research / "config.yaml").write_text("mode: autonomous\n")
    (research / "idea_pool.json").write_text(json.dumps({"ideas": []}))
    (research / "results.tsv").write_text("header\n")
    (research / "worktrees").mkdir()
    (research / "run.log").write_text("")
    scripts = research / "scripts"
    scripts.mkdir()
    (scripts / "record.py").write_text("")
    return research


def test_create_and_remove_worktree():
    """Worktree is created with a shared .research symlink and cleaned up."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _init_git_repo(repo)
        _setup_research(repo)

        wt_path = create_worktree(repo, "test-worker")

        # Worktree exists and has the committed file
        assert wt_path.exists()
        assert (wt_path / "hello.py").exists()

        # .research/ is a directory symlink to the canonical shared state
        wt_research = wt_path / ".research"
        assert wt_research.is_dir()
        assert os.path.islink(str(wt_research))
        assert wt_research.resolve() == (repo / ".research").resolve()
        assert (wt_research / "idea_pool.json").exists()
        assert (wt_research / "config.yaml").exists()
        assert (wt_research / "experiment_program.md").exists()
        assert (wt_research / "results.tsv").exists()
        assert (wt_research / "scripts").exists()

        # Clean up
        remove_worktree(repo, wt_path)
        assert not wt_path.exists()


def test_worktree_shares_idea_pool():
    """IdeaPool updates in the worktree hit the canonical shared state."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _init_git_repo(repo)
        research = _setup_research(repo)

        wt_path = create_worktree(repo, "share-test")
        wt_pool = IdeaPool(wt_path / ".research" / "idea_pool.json")
        wt_pool.add("shared idea", priority=1)

        main_data = json.loads((research / "idea_pool.json").read_text())
        assert len(main_data["ideas"]) == 1
        assert main_data["ideas"][0]["description"] == "shared idea"

        remove_worktree(repo, wt_path)


def test_worktree_shares_atomic_progress_updates():
    """Atomic writes in a worktree update the canonical progress file."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _init_git_repo(repo)
        research = _setup_research(repo)
        progress = research / "experiment_progress.json"
        progress.write_text(json.dumps({"phase": "init"}))

        wt_path = create_worktree(repo, "progress-test")
        wt_progress = wt_path / ".research" / "experiment_progress.json"

        atomic_write_json(wt_progress, {"phase": "experimenting"})

        assert json.loads(progress.read_text()) == {"phase": "experimenting"}
        assert wt_progress.resolve() == progress.resolve()

        remove_worktree(repo, wt_path)


def test_worktree_code_isolation():
    """Code changes in one worktree don't affect another or main repo."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _init_git_repo(repo)
        _setup_research(repo)

        wt1 = create_worktree(repo, "worker-0")
        wt2 = create_worktree(repo, "worker-1")

        # Modify hello.py differently in each worktree
        (wt1 / "hello.py").write_text("print('from worker 0')\n")
        (wt2 / "hello.py").write_text("print('from worker 1')\n")

        # Main repo is unchanged
        assert (repo / "hello.py").read_text() == "print('hello')\n"

        # Each worktree has its own version
        assert "worker 0" in (wt1 / "hello.py").read_text()
        assert "worker 1" in (wt2 / "hello.py").read_text()

        remove_worktree(repo, wt1)
        remove_worktree(repo, wt2)


def test_worktree_stale_cleanup():
    """Creating a worktree with existing name removes the stale one first."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _init_git_repo(repo)
        _setup_research(repo)

        wt1 = create_worktree(repo, "reuse-test")
        (wt1 / "hello.py").write_text("modified\n")

        # Create again with same name — should succeed
        wt2 = create_worktree(repo, "reuse-test")
        assert wt2.exists()
        # Should have fresh checkout
        assert (wt2 / "hello.py").read_text() == "print('hello')\n"

        remove_worktree(repo, wt2)


def test_worker_uses_worktree_isolation():
    """WorkerManager runs each experiment in an isolated worktree."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _init_git_repo(repo)
        research = _setup_research(repo)

        from open_researcher.worker import WorkerManager

        ideas = [
            {"id": "idea-001", "description": "Test idea", "status": "pending",
             "priority": 1, "claimed_by": None, "assigned_experiment": None,
             "result": None, "source": "original", "category": "general",
             "gpu_hint": "auto", "created_at": "2026-01-01T00:00:00"},
        ]
        pool_path = research / "idea_pool.json"
        pool_path.write_text(json.dumps({"ideas": ideas}, indent=2))
        idea_pool = IdeaPool(pool_path)

        mock_gpu_manager = MagicMock()
        mock_gpu_manager.refresh.return_value = []

        workdirs_used = []

        def mock_agent_factory():
            agent = MagicMock()

            def run_fn(workdir, on_output=None, program_file="program.md", **kwargs):
                workdirs_used.append(str(workdir))
                return 0

            agent.run.side_effect = run_fn
            return agent

        output_lines = []
        wm = WorkerManager(
            repo_path=repo,
            research_dir=research,
            gpu_manager=mock_gpu_manager,
            idea_pool=idea_pool,
            agent_factory=mock_agent_factory,
            max_workers=1,
            on_output=output_lines.append,
        )

        wm.start()
        wm.join(timeout=10)

        # Agent should have run in a worktree, not the main repo
        assert len(workdirs_used) == 1
        assert workdirs_used[0] != str(repo)
        assert str(worktrees_root(repo)) in workdirs_used[0]

        # Worktree should be cleaned up
        root = worktrees_root(repo)
        if root.exists():
            remaining = list(root.iterdir())
            assert len(remaining) == 0, f"Stale worktrees: {remaining}"

        # Idea should be marked done
        summary = idea_pool.summary()
        assert summary["done"] == 1
