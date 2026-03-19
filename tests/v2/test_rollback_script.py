"""Tests for the rollback.sh helper script."""

from __future__ import annotations

from pathlib import Path


class TestRollbackScript:
    """Verify rollback.sh exists, is executable, and has correct content."""

    def _script_path(self) -> Path:
        return (
            Path(__file__).resolve().parents[2]
            / "src" / "open_researcher_v2" / "skills" / "scripts" / "rollback.sh"
        )

    def test_exists(self):
        assert self._script_path().exists()

    def test_is_executable(self):
        import os
        assert os.access(self._script_path(), os.X_OK)

    def test_contains_git_checkout(self):
        content = self._script_path().read_text(encoding="utf-8")
        assert "git checkout" in content

    def test_excludes_research_dir(self):
        content = self._script_path().read_text(encoding="utf-8")
        assert "--exclude=.research" in content

    def test_has_shebang(self):
        content = self._script_path().read_text(encoding="utf-8")
        assert content.startswith("#!/usr/bin/env bash")

    def test_has_set_euo_pipefail(self):
        content = self._script_path().read_text(encoding="utf-8")
        assert "set -euo pipefail" in content
