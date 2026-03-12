"""Git workspace safety helpers for experiment runtime."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

_RUNTIME_STATE_PREFIXES = (".research",)


class GitWorkspaceError(RuntimeError):
    """Raised when the experiment workspace is not safe to use."""


@dataclass(frozen=True, slots=True)
class GitWorkspaceSnapshot:
    """Minimal git snapshot required to restore a workspace."""

    head: str


@dataclass(frozen=True, slots=True)
class GitStatusEntry:
    """One porcelain status entry."""

    code: str
    path: str


def capture_clean_workspace_snapshot(repo_path: Path) -> GitWorkspaceSnapshot:
    """Capture HEAD after verifying the workspace is clean enough for runtime."""
    head = _run_git(repo_path, "rev-parse", "HEAD").stdout.strip()
    ensure_clean_workspace(repo_path, context="before experiment")
    return GitWorkspaceSnapshot(head=head)


def ensure_clean_workspace(repo_path: Path, *, context: str) -> None:
    """Raise when the workspace contains non-runtime changes."""
    changes = _workspace_changes(repo_path)
    if changes:
        raise GitWorkspaceError(f"Git workspace {context} is dirty: {_format_changes(changes)}")


def rollback_workspace(repo_path: Path, snapshot: GitWorkspaceSnapshot) -> None:
    """Restore the workspace back to the recorded snapshot, preserving .research."""
    _run_git(repo_path, "reset", "--hard", snapshot.head)
    for entry in _workspace_changes(repo_path):
        _remove_path(repo_path, entry.path)
    ensure_clean_workspace(repo_path, context="after rollback")


def _run_git(repo_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown git error"
        raise GitWorkspaceError(f"git {' '.join(args)} failed: {detail}")
    return result


def _workspace_changes(repo_path: Path) -> list[GitStatusEntry]:
    result = _run_git(repo_path, "status", "--porcelain=v1", "--untracked-files=all")
    changes: list[GitStatusEntry] = []
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        code = line[:2]
        path = line[3:]
        if " -> " in path and ("R" in code or "C" in code):
            _old_path, path = path.split(" -> ", 1)
        normalized = _normalize_path(path)
        if normalized and not _is_runtime_state_path(normalized):
            changes.append(GitStatusEntry(code=code, path=normalized))
    return changes


def _normalize_path(raw_path: str) -> str:
    normalized = raw_path.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _is_runtime_state_path(path: str) -> bool:
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in _RUNTIME_STATE_PREFIXES)


def _format_changes(changes: list[GitStatusEntry], *, limit: int = 5) -> str:
    preview = [f"{entry.code} {entry.path}" for entry in changes[:limit]]
    if len(changes) > limit:
        preview.append(f"... +{len(changes) - limit} more")
    return ", ".join(preview)


def _remove_path(repo_path: Path, relative_path: str) -> None:
    root = repo_path.resolve()
    target = (root / relative_path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise GitWorkspaceError(f"Refusing to remove path outside repo: {relative_path}") from exc
    if not target.exists() and not target.is_symlink():
        return
    if target.is_symlink() or target.is_file():
        target.unlink()
        return
    shutil.rmtree(target)
