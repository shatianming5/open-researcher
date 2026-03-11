"""Git worktree helpers for parallel experiment isolation."""

import hashlib
import logging
import os
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_WORKTREE_ROOT_PREFIX = ".open-researcher-worktrees-"


def worktrees_root(repo_path: Path) -> Path:
    """Return the external root used for isolated experiment worktrees."""
    resolved_repo = repo_path.resolve()
    digest = hashlib.sha1(str(resolved_repo).encode("utf-8")).hexdigest()[:10]
    dirname = f"{_WORKTREE_ROOT_PREFIX}{resolved_repo.name}-{digest}"
    return resolved_repo.parent / dirname


def create_worktree(repo_path: Path, worktree_name: str) -> Path:
    """Create an isolated git worktree for a parallel worker.

    Creates a new branch and worktree under an external worktree root.
    Replaces the worktree's `.research/` directory with a directory symlink
    back to the canonical repo state so atomic writes and lock files stay
    shared across workers.

    Returns the worktree path.
    """
    research_dir = repo_path / ".research"
    worktrees_dir = worktrees_root(repo_path)
    worktrees_dir.mkdir(parents=True, exist_ok=True)
    wt_path = worktrees_dir / worktree_name
    branch_name = f"or-worker-{worktree_name}"

    # Remove stale worktree if it exists
    if wt_path.exists():
        remove_worktree(repo_path, wt_path)

    # Create worktree with a new branch from HEAD
    subprocess.run(
        ["git", "worktree", "add", "-b", branch_name, str(wt_path), "HEAD"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        check=True,
    )

    # Replace the checked-out .research tree with a shared directory symlink so
    # all state files and their companion *.lock files resolve canonically.
    _replace_research_dir(wt_path, research_dir)

    logger.debug("Created worktree %s (branch %s)", wt_path, branch_name)
    return wt_path


def _replace_research_dir(worktree_path: Path, research_dir: Path) -> None:
    """Replace the worktree's .research directory with a shared symlink."""
    wt_research = worktree_path / ".research"
    if wt_research.is_symlink() or wt_research.is_file():
        wt_research.unlink()
    elif wt_research.is_dir():
        shutil.rmtree(wt_research)
    os.symlink(str(research_dir.resolve()), str(wt_research))


def remove_worktree(repo_path: Path, worktree_path: Path) -> None:
    """Remove a git worktree and its branch."""
    wt_name = worktree_path.name
    branch_name = f"or-worker-{wt_name}"

    # Remove the shared .research symlink first (git worktree remove dislikes it)
    wt_research = worktree_path / ".research"
    if wt_research.is_symlink() or wt_research.is_file():
        wt_research.unlink()
    elif wt_research.is_dir():
        shutil.rmtree(wt_research, ignore_errors=True)

    # Remove worktree
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree_path)],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
    )

    # Delete the temporary branch
    subprocess.run(
        ["git", "branch", "-D", branch_name],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
    )

    root = worktree_path.parent
    if root.exists() and root.name.startswith(_WORKTREE_ROOT_PREFIX):
        try:
            next(root.iterdir())
        except StopIteration:
            root.rmdir()

    logger.debug("Removed worktree %s", worktree_path)
