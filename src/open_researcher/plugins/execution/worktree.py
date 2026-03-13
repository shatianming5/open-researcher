"""Git worktree management for isolated experiment execution."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class WorktreeInfo:
    """Represents an active git worktree."""

    path: Path
    branch: str
    commit: str


def create_worktree(
    repo_path: Path, name: str, *, base_ref: str = "HEAD"
) -> WorktreeInfo:
    """Create a new git worktree for isolated execution.

    Args:
        repo_path: Path to the main repository
        name: Name for the worktree (used in branch and directory name)
        base_ref: Git ref to base the worktree on

    Returns:
        WorktreeInfo with the path, branch, and commit of the new worktree
    """
    worktree_dir = repo_path / ".worktrees" / name
    branch_name = f"experiment/{name}"

    subprocess.run(
        ["git", "worktree", "add", "-b", branch_name, str(worktree_dir), base_ref],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )

    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=worktree_dir,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    return WorktreeInfo(path=worktree_dir, branch=branch_name, commit=commit)


def remove_worktree(repo_path: Path, name: str) -> None:
    """Remove a git worktree and its branch."""
    worktree_dir = repo_path / ".worktrees" / name

    subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree_dir)],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )

    branch_name = f"experiment/{name}"
    subprocess.run(
        ["git", "branch", "-D", branch_name],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )


def list_worktrees(repo_path: Path) -> list[WorktreeInfo]:
    """List all active worktrees for a repository."""
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )

    worktrees: list[WorktreeInfo] = []
    current: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            if current:
                worktrees.append(
                    WorktreeInfo(
                        path=Path(current.get("worktree", "")),
                        branch=current.get("branch", "").replace(
                            "refs/heads/", ""
                        ),
                        commit=current.get("HEAD", ""),
                    )
                )
            current = {"worktree": line.split(" ", 1)[1]}
        elif line.startswith("HEAD "):
            current["HEAD"] = line.split(" ", 1)[1]
        elif line.startswith("branch "):
            current["branch"] = line.split(" ", 1)[1]

    if current:
        worktrees.append(
            WorktreeInfo(
                path=Path(current.get("worktree", "")),
                branch=current.get("branch", "").replace("refs/heads/", ""),
                commit=current.get("HEAD", ""),
            )
        )

    return worktrees
