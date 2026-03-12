"""Helpers for ensuring a repository has a usable local git identity."""

from __future__ import annotations

import subprocess
from pathlib import Path


def ensure_local_git_identity(repo_path: Path) -> dict[str, str]:
    """Ensure ``user.name`` and ``user.email`` exist in the repo's local config.

    Values are inherited from the latest commit metadata when available so agent
    commits stay attributable without requiring global git configuration.
    """

    existing_name = _git_config_get(repo_path, "user.name")
    existing_email = _git_config_get(repo_path, "user.email")
    if existing_name and existing_email:
        return {"name": existing_name, "email": existing_email, "source": "existing_local_config"}

    fallback_name = _git_log_value(repo_path, "%an") or "Experiment Agent"
    fallback_email = _git_log_value(repo_path, "%ae") or "experiment.agent@local"

    name = existing_name or fallback_name
    email = existing_email or fallback_email

    if not existing_name:
        _git_config_set(repo_path, "user.name", name)
    if not existing_email:
        _git_config_set(repo_path, "user.email", email)

    return {
        "name": name,
        "email": email,
        "source": "latest_commit_metadata",
    }


def _git_config_get(repo_path: Path, key: str) -> str:
    result = subprocess.run(
        ["git", "config", "--local", "--get", key],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _git_log_value(repo_path: Path, fmt: str) -> str:
    result = subprocess.run(
        ["git", "log", "-1", f"--pretty=format:{fmt}"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _git_config_set(repo_path: Path, key: str, value: str) -> None:
    subprocess.run(
        ["git", "config", "--local", key, value],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        check=True,
    )
