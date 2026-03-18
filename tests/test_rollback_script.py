"""Tests for the rollback.sh helper script."""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

ROLLBACK_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "paperfarm"
    / "skills"
    / "scripts"
    / "rollback.sh"
)


class TestRollbackScript:
    def test_script_exists(self) -> None:
        assert ROLLBACK_SCRIPT.exists()

    def test_script_is_executable(self) -> None:
        mode = os.stat(ROLLBACK_SCRIPT).st_mode
        assert mode & stat.S_IXUSR, "rollback.sh should be executable"

    def test_contains_git_checkout(self) -> None:
        content = ROLLBACK_SCRIPT.read_text()
        assert "git checkout" in content

    def test_excludes_research_dir(self) -> None:
        content = ROLLBACK_SCRIPT.read_text()
        assert "--exclude=.research" in content

    def test_has_shebang(self) -> None:
        content = ROLLBACK_SCRIPT.read_text()
        assert content.startswith("#!/usr/bin/env bash")

    def test_has_strict_mode(self) -> None:
        content = ROLLBACK_SCRIPT.read_text()
        assert "set -euo pipefail" in content
