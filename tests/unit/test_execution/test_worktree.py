"""Tests for worktree management (unit-level, no real git repos)."""
import pytest

from open_researcher.plugins.execution.worktree import WorktreeInfo


def test_worktree_info_creation():
    from pathlib import Path

    info = WorktreeInfo(
        path=Path("/tmp/test-worktree"),
        branch="experiment/test-1",
        commit="abc123",
    )
    assert info.path == Path("/tmp/test-worktree")
    assert info.branch == "experiment/test-1"
    assert info.commit == "abc123"


def test_worktree_info_is_frozen():
    from pathlib import Path

    info = WorktreeInfo(path=Path("/tmp"), branch="main", commit="abc")
    with pytest.raises(AttributeError):
        info.branch = "other"  # type: ignore[misc]
