"""Shared helpers for runtime-state and artifact paths."""

from __future__ import annotations

import hashlib
from pathlib import PurePosixPath
from typing import Any

RUNTIME_OUTPUT_ROOTS = (
    "work_dirs",
    "outputs",
    "runs",
    "artifacts",
    "checkpoints",
    "logs",
    "log",
    "wandb",
    ".wandb",
    "coverage",
    "htmlcov",
)

OVERLAY_MANIFEST_FILENAME = "open_researcher_overlay_manifest.json"

OVERLAY_SKIP_PARTS = {
    ".git",
    ".research",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".tox",
    ".nox",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
    "coverage",
    "htmlcov",
    "wandb",
    ".wandb",
    "work_dirs",
    "outputs",
    "runs",
    "artifacts",
    "checkpoints",
    "logs",
    "log",
    "tmp",
    "temp",
    "dataset",
    "datasets",
    "data",
}


def normalize_relative_path(raw_path: str) -> str:
    normalized = raw_path.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def is_runtime_state_path(path: str) -> bool:
    normalized = normalize_relative_path(path)
    if not normalized:
        return False
    first = _first_path_part(normalized)
    return first == ".research" or first.startswith(".research.bak_")


def is_runtime_artifact_path(path: str) -> bool:
    normalized = normalize_relative_path(path)
    if not normalized:
        return False
    first = _first_path_part(normalized)
    return is_runtime_state_path(normalized) or first in RUNTIME_OUTPUT_ROOTS


def should_skip_overlay_path(path: str) -> bool:
    normalized = normalize_relative_path(path)
    if not normalized:
        return False
    for part in PurePosixPath(normalized).parts:
        if part == ".research" or part.startswith(".research.bak_"):
            return True
        if part in OVERLAY_SKIP_PARTS:
            return True
    return False


def runtime_git_exclude_patterns() -> list[str]:
    patterns = ["/.research", "/.research/", "/.research.bak_*", "/.research.bak_*/"]
    for root in RUNTIME_OUTPUT_ROOTS:
        patterns.append(f"/{root}")
        patterns.append(f"/{root}/")
    return patterns


def runtime_output_roots() -> tuple[str, ...]:
    return RUNTIME_OUTPUT_ROOTS


def _first_path_part(path: str) -> str:
    parts = PurePosixPath(path).parts
    return parts[0] if parts else ""


def overlay_manifest_entry_for_path(path) -> dict[str, Any] | None:
    try:
        if path.is_symlink():
            return {"kind": "symlink", "target": str(path.readlink())}
        if not path.is_file():
            return None
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return {"kind": "file", "size": int(path.stat().st_size), "sha256": digest.hexdigest()}
    except OSError:
        return None
