"""Git worktree helpers for parallel experiment isolation.

Migrated from ``open_researcher.worktree``.  This is the full-featured
worktree manager used by the original research loop.
"""

import json
import hashlib
import logging
import os
import shutil
import subprocess
from pathlib import Path

from open_researcher.workspace_paths import (
    OVERLAY_MANIFEST_FILENAME,
    normalize_relative_path,
    overlay_manifest_entry_for_path,
    runtime_git_exclude_patterns,
    runtime_output_roots,
    should_skip_overlay_path,
)

logger = logging.getLogger(__name__)

_WORKTREE_ROOT_PREFIX = ".open-researcher-worktrees-"
_WORKTREE_EXCLUDE_PATTERNS = tuple(runtime_git_exclude_patterns())
_OVERLAY_ALLOWED_FILENAMES = {
    ".env",
    ".envrc",
    ".python-version",
    ".tool-versions",
    "Dockerfile",
    "Makefile",
}
_OVERLAY_ALLOWED_SUFFIXES = {
    ".bash",
    ".c",
    ".cc",
    ".cfg",
    ".cpp",
    ".cu",
    ".go",
    ".h",
    ".hpp",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".kt",
    ".md",
    ".mjs",
    ".py",
    ".pyi",
    ".pyx",
    ".pxd",
    ".rb",
    ".rs",
    ".scala",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
    ".zsh",
}
_OVERLAY_MAX_BYTES = 4 * 1024 * 1024


class WorktreeError(RuntimeError):
    """Raised when isolated worktree setup or cleanup fails."""


def worktrees_root(repo_path: Path) -> Path:
    """Return the external root used for isolated experiment worktrees."""
    resolved_repo = repo_path.resolve()
    digest = hashlib.sha1(str(resolved_repo).encode("utf-8")).hexdigest()[:10]
    dirname = f"{_WORKTREE_ROOT_PREFIX}{resolved_repo.name}-{digest}"
    return resolved_repo.parent / dirname


def create_worktree(repo_path: Path, worktree_name: str) -> Path:
    """Create an isolated git worktree for a parallel worker.

    Creates a new branch and worktree under an external worktree root.
    Replaces the worktree's ``.research/`` directory with a directory symlink
    back to the canonical repo state so atomic writes and lock files stay
    shared across workers.

    Returns the worktree path.
    """
    research_dir = repo_path / ".research"
    worktrees_dir = worktrees_root(repo_path)
    worktrees_dir.mkdir(parents=True, exist_ok=True)
    wt_path = worktrees_dir / worktree_name
    branch_name = f"or-worker-{worktree_name}"

    _run_git(repo_path, "worktree", "prune")

    # Remove stale worktree if it exists
    if wt_path.exists():
        remove_worktree(repo_path, wt_path)
    elif _branch_exists(repo_path, branch_name):
        _run_git(repo_path, "branch", "-D", branch_name)

    _run_git(repo_path, "worktree", "add", "-b", branch_name, str(wt_path), "HEAD")

    try:
        # Replace the checked-out .research tree with a shared directory symlink so
        # all state files and their companion *.lock files resolve canonically.
        _replace_research_dir(wt_path, research_dir)
        _ensure_worktree_exclude_patterns(wt_path, _WORKTREE_EXCLUDE_PATTERNS)
        synced_overlay_paths = _sync_source_overlays(repo_path, wt_path)
        _sanitize_runtime_artifacts(wt_path)
        _mark_runtime_artifacts_skip_worktree(wt_path)
        _write_overlay_manifest(wt_path, synced_overlay_paths)
    except Exception as exc:
        try:
            remove_worktree(repo_path, wt_path)
        except Exception as cleanup_exc:  # pragma: no cover - best-effort context enrichment
            raise WorktreeError(
                f"Failed to finish worktree setup ({exc}) and cleanup failed ({cleanup_exc})"
            ) from cleanup_exc
        raise WorktreeError(f"Failed to finish worktree setup: {exc}") from exc

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


def _ensure_worktree_exclude_patterns(worktree_path: Path, patterns: tuple[str, ...]) -> None:
    for exclude_path in _git_info_exclude_paths(worktree_path):
        exclude_path.parent.mkdir(parents=True, exist_ok=True)
        existing_text = exclude_path.read_text(encoding="utf-8") if exclude_path.exists() else ""
        existing = {line.strip() for line in existing_text.splitlines() if line.strip()}
        missing = [pattern for pattern in patterns if pattern not in existing]
        if not missing:
            continue
        with exclude_path.open("a", encoding="utf-8") as f:
            if existing_text and not existing_text.endswith("\n"):
                f.write("\n")
            for pattern in missing:
                f.write(f"{pattern}\n")


def _git_info_exclude_paths(repo_path: Path) -> list[Path]:
    candidates: list[Path] = []
    for rev_arg in ("--git-dir", "--git-common-dir"):
        result = subprocess.run(
            ["git", "rev-parse", rev_arg],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            continue
        git_dir = Path(result.stdout.strip())
        if not git_dir.is_absolute():
            git_dir = (repo_path / git_dir).resolve()
        exclude_path = git_dir / "info" / "exclude"
        if exclude_path not in candidates:
            candidates.append(exclude_path)
    return candidates


def _sync_source_overlays(repo_path: Path, worktree_path: Path) -> list[Path]:
    patch = subprocess.run(
        ["git", "diff", "--binary", "HEAD", "--"],
        cwd=str(repo_path),
        capture_output=True,
        text=False,
        timeout=120,
    )
    if patch.returncode != 0:
        detail = patch.stderr.decode("utf-8", errors="replace").strip()
        raise WorktreeError(f"git diff --binary HEAD failed: {detail or 'unknown git diff error'}")
    if patch.stdout:
        applied = subprocess.run(
            ["git", "apply", "--binary", "-"],
            cwd=str(worktree_path),
            input=patch.stdout,
            capture_output=True,
            text=False,
            timeout=120,
        )
        if applied.returncode != 0:
            detail = applied.stderr.decode("utf-8", errors="replace").strip()
            raise WorktreeError(f"Failed to apply working tree patch: {detail or 'unknown git apply error'}")

    overlay_paths = _iter_untracked_overlay_paths(repo_path)
    for relative_path in overlay_paths:
        source = repo_path / relative_path
        target = worktree_path / relative_path
        _copy_overlay_path(source, target)
    return overlay_paths


def _iter_untracked_overlay_paths(repo_path: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all", "--ignored=matching"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown git status error"
        raise WorktreeError(f"git status for overlay sync failed: {detail}")

    overlay_paths: list[Path] = []
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        code = line[:2]
        if code not in {"??", "!!"}:
            continue
        normalized = normalize_relative_path(line[3:])
        if not normalized:
            continue
        relative = Path(normalized)
        source = repo_path / relative
        if not _should_copy_overlay_path(relative, source):
            continue
        overlay_paths.append(relative)
    return sorted(set(overlay_paths))

def _should_copy_overlay_path(relative_path: Path, source: Path) -> bool:
    normalized = relative_path.as_posix()
    if should_skip_overlay_path(normalized):
        return False
    if not source.exists() and not source.is_symlink():
        return False
    if source.is_dir():
        return False
    if source.is_file() and source.stat().st_size > _OVERLAY_MAX_BYTES:
        return False
    if relative_path.name in _OVERLAY_ALLOWED_FILENAMES:
        return True
    return relative_path.suffix.lower() in _OVERLAY_ALLOWED_SUFFIXES


def _copy_overlay_path(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    _remove_existing_path(target)
    if source.is_symlink():
        os.symlink(os.readlink(source), target)
        return
    shutil.copy2(source, target)


def _remove_existing_path(target: Path) -> None:
    if target.is_symlink() or target.is_file():
        target.unlink()
        return
    if target.is_dir():
        shutil.rmtree(target)


def _sanitize_runtime_artifacts(worktree_path: Path) -> None:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=str(worktree_path),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown git status error"
        raise WorktreeError(f"git status for runtime artifact cleanup failed: {detail}")

    tracked_to_restore: list[str] = []
    untracked_to_remove: list[str] = []
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        code = line[:2]
        path = line[3:]
        if " -> " in path and ("R" in code or "C" in code):
            _old_path, path = path.split(" -> ", 1)
        normalized = normalize_relative_path(path)
        if not normalized or not should_skip_overlay_path(normalized):
            continue
        if code in {"??", "!!"}:
            untracked_to_remove.append(normalized)
        else:
            tracked_to_restore.append(normalized)

    for path in sorted(set(untracked_to_remove), reverse=True):
        _remove_existing_path(worktree_path / path)
    if tracked_to_restore:
        _run_git(worktree_path, "checkout", "--", *sorted(set(tracked_to_restore)))


def _mark_runtime_artifacts_skip_worktree(worktree_path: Path) -> None:
    roots = list(runtime_output_roots())
    if not roots:
        return
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", *roots],
        cwd=str(worktree_path),
        capture_output=True,
        text=False,
        timeout=120,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise WorktreeError(f"git ls-files for runtime artifact paths failed: {detail or 'unknown git error'}")
    paths = [item.decode("utf-8", errors="replace") for item in result.stdout.split(b"\x00") if item]
    if not paths:
        return
    chunk_size = 256
    for start in range(0, len(paths), chunk_size):
        chunk = paths[start : start + chunk_size]
        _run_git(worktree_path, "update-index", "--skip-worktree", "--", *chunk)


def _write_overlay_manifest(worktree_path: Path, overlay_paths: list[Path]) -> None:
    manifest_path = _git_overlay_manifest_path(worktree_path)
    if manifest_path is None:
        return
    payload = {"paths": {}}
    for relative_path in overlay_paths:
        entry = overlay_manifest_entry_for_path(worktree_path / relative_path)
        if entry is None:
            continue
        payload["paths"][relative_path.as_posix()] = entry
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _git_overlay_manifest_path(repo_path: Path) -> Path | None:
    candidates = _git_info_exclude_paths(repo_path)
    if not candidates:
        return None
    return candidates[0].parent.parent / OVERLAY_MANIFEST_FILENAME


def remove_worktree(repo_path: Path, worktree_path: Path) -> None:
    """Remove a git worktree and its branch."""
    wt_name = worktree_path.name
    branch_name = f"or-worker-{wt_name}"
    _run_git(repo_path, "worktree", "prune")

    # Remove the shared .research symlink first (git worktree remove dislikes it)
    wt_research = worktree_path / ".research"
    if wt_research.is_symlink() or wt_research.is_file():
        wt_research.unlink()
    elif wt_research.is_dir():
        shutil.rmtree(wt_research, ignore_errors=True)

    if worktree_path.exists():
        result = subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree_path)],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0 and worktree_path.exists():
            shutil.rmtree(worktree_path, ignore_errors=True)
        if worktree_path.exists():
            detail = result.stderr.strip() or result.stdout.strip() or "unknown git error"
            raise WorktreeError(f"Failed to remove worktree {worktree_path}: {detail}")

    _run_git(repo_path, "worktree", "prune")
    if _branch_exists(repo_path, branch_name):
        _run_git(repo_path, "branch", "-D", branch_name)

    root = worktree_path.parent
    if root.exists() and root.name.startswith(_WORKTREE_ROOT_PREFIX):
        try:
            next(root.iterdir())
        except StopIteration:
            root.rmdir()

    logger.debug("Removed worktree %s", worktree_path)


def _branch_exists(repo_path: Path, branch_name: str) -> bool:
    result = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode == 0


def _run_git(repo_path: Path, *args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise WorktreeError(f"git {' '.join(args)} timed out after {timeout}s") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown git error"
        raise WorktreeError(f"git {' '.join(args)} failed: {detail}")
    return result
