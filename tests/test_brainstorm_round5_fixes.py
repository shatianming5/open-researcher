"""Tests for brainstorm round 5 P0+P1 fixes across kernel, storage, runtime, and safety modules."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import sqlite3
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── EventBus task tracking ──


class TestEventBusTaskTracking:
    """P0: EventBus must track async handler tasks to prevent GC collection."""

    def test_pending_tasks_set_exists(self):
        from open_researcher.kernel.bus import EventBus
        from open_researcher.kernel.store import EventStore

        store = EventStore(":memory:")
        bus = EventBus(store)
        assert hasattr(bus, "_pending_tasks")
        assert isinstance(bus._pending_tasks, set)

    def test_task_added_and_removed(self):
        from open_researcher.kernel.bus import EventBus
        from open_researcher.kernel.event import Event
        from open_researcher.kernel.store import EventStore

        store = EventStore(":memory:")
        bus = EventBus(store)

        results = []

        async def async_handler(event):
            results.append(event.type)

        bus.on("test.*", async_handler)

        async def _run():
            await store.open()
            event = Event(type="test.foo", payload={})
            await bus.emit(event)
            # Let event loop process the dispatched tasks
            await asyncio.sleep(0.1)
            return results

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(_run())
        finally:
            loop.close()
        assert result == ["test.foo"]
        # After completion, task should have been cleaned up
        assert len(bus._pending_tasks) == 0

    def test_source_uses_discard_callback(self):
        source = inspect.getsource(
            __import__("open_researcher.kernel.bus", fromlist=["EventBus"]).EventBus
        )
        assert "add_done_callback" in source
        assert "_pending_tasks.discard" in source


# ── EventStore thread safety ──


class TestEventStoreThreadSafety:
    """P0: EventStore must use threading.Lock for SQLite access."""

    def test_has_lock(self):
        from open_researcher.kernel.store import EventStore

        store = EventStore(":memory:")
        assert hasattr(store, "_lock")
        assert isinstance(store._lock, type(threading.Lock()))

    def test_concurrent_appends(self):
        from open_researcher.kernel.event import Event
        from open_researcher.kernel.store import EventStore

        store = EventStore(":memory:")

        async def _run():
            await store.open()
            tasks = []
            for i in range(20):
                event = Event(type=f"test.{i}", payload={"i": i})
                tasks.append(store.append(event))
            await asyncio.gather(*tasks)
            count = await store.count()
            await store.close()
            return count

        loop = asyncio.new_event_loop()
        try:
            count = loop.run_until_complete(_run())
        finally:
            loop.close()
        assert count == 20

    def test_lock_in_source(self):
        source = inspect.getsource(
            __import__("open_researcher.kernel.store", fromlist=["EventStore"]).EventStore
        )
        assert "self._lock" in source
        assert "with self._lock:" in source


# ── Database thread safety ──


class TestDatabaseThreadSafety:
    """P0: Database must expose a lock for thread-safe access."""

    def test_has_lock(self):
        from open_researcher.plugins.storage.db import Database

        db = Database(":memory:")
        assert hasattr(db, "lock")
        assert isinstance(db.lock, type(threading.Lock()))


# ── GraphStore uses db.lock ──


class TestGraphStoreLocking:
    """P0: GraphStore operations must use db.lock."""

    def test_lock_in_source(self):
        source = inspect.getsource(
            __import__("open_researcher.plugins.graph.store", fromlist=["GraphStore"]).GraphStore
        )
        assert "self._db.lock" in source


# ── launch_detached fsync ──


class TestLaunchDetachedAtomicWrite:
    """P0: _atomic_write_json must use fsync for durability."""

    def test_fsync_in_source(self):
        from open_researcher.scripts import launch_detached

        source = inspect.getsource(launch_detached._atomic_write_json)
        assert "os.fsync" in source
        assert "os.replace" in source

    def test_atomic_write_json(self, tmp_path):
        from open_researcher.scripts.launch_detached import _atomic_write_json

        target = tmp_path / "state.json"
        _atomic_write_json(target, {"status": "running", "pid": 12345})
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data["status"] == "running"
        assert data["pid"] == 12345

    def test_no_tmp_files_on_success(self, tmp_path):
        from open_researcher.scripts.launch_detached import _atomic_write_json

        target = tmp_path / "state.json"
        _atomic_write_json(target, {"ok": True})
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []

    def test_cleanup_on_error(self, tmp_path):
        from open_researcher.scripts.launch_detached import _atomic_write_json

        target = tmp_path / "state.json"
        # Write initial content
        _atomic_write_json(target, {"initial": True})

        # Simulate failure during write by patching os.replace to fail
        with patch("os.replace", side_effect=OSError("disk full")):
            with pytest.raises(OSError, match="disk full"):
                _atomic_write_json(target, {"should_fail": True})

        # Original file should still be intact
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data["initial"] is True
        # No .tmp files should remain
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []


# ── Git subprocess timeout ──


class TestGitSubprocessTimeout:
    """P0: Git subprocess calls must have timeout parameter."""

    def test_safety_run_git_timeout(self):
        source = inspect.getsource(
            __import__("open_researcher.plugins.orchestrator.safety", fromlist=["_run_git"])._run_git
        )
        assert "timeout=" in source
        assert "TimeoutExpired" in source

    def test_worktree_run_git_timeout(self):
        source = inspect.getsource(
            __import__(
                "open_researcher.plugins.execution.legacy_worktree", fromlist=["_run_git"]
            )._run_git
        )
        assert "timeout=" in source
        assert "TimeoutExpired" in source

    def test_safety_overlay_manifest_timeout(self):
        source = inspect.getsource(
            __import__(
                "open_researcher.plugins.orchestrator.safety", fromlist=["_overlay_manifest_path"]
            )._overlay_manifest_path
        )
        assert "timeout=" in source

    def test_worktree_diff_timeout(self):
        source = inspect.getsource(
            __import__(
                "open_researcher.plugins.execution.legacy_worktree",
                fromlist=["_sync_source_overlays"],
            )._sync_source_overlays
        )
        assert "timeout=" in source


# ── Kernel boot exception handling ──


class TestKernelBootExceptionHandling:
    """P1: Kernel.boot() must roll back on plugin failure."""

    def test_boot_rolls_back_on_failure(self):
        from open_researcher.kernel.kernel import Kernel
        from open_researcher.kernel.plugin import PluginBase

        class GoodPlugin(PluginBase):
            name = "good"
            started = False
            stopped = False

            async def start(self, kernel):
                GoodPlugin.started = True

            async def stop(self):
                GoodPlugin.stopped = True

        class BadPlugin(PluginBase):
            name = "bad"

            async def start(self, kernel):
                raise RuntimeError("plugin crash")

            async def stop(self):
                pass

        kernel = Kernel()

        async def _run():
            with pytest.raises(RuntimeError, match="plugin crash"):
                await kernel.boot([GoodPlugin(), BadPlugin()])

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_run())
        finally:
            loop.close()
        assert GoodPlugin.started
        assert GoodPlugin.stopped  # rollback should have stopped it

    def test_shutdown_survives_plugin_error(self):
        from open_researcher.kernel.kernel import Kernel
        from open_researcher.kernel.plugin import PluginBase

        class CrashOnStop(PluginBase):
            name = "crash_stop"

            async def start(self, kernel):
                pass

            async def stop(self):
                raise RuntimeError("stop crash")

        kernel = Kernel()

        async def _run():
            await kernel.boot([CrashOnStop()])
            # Should not raise even though stop() crashes
            await kernel.shutdown()

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_run())
        finally:
            loop.close()

    def test_started_plugins_tracked(self):
        from open_researcher.kernel.kernel import Kernel

        kernel = Kernel()
        assert hasattr(kernel, "_started_plugins")
        assert isinstance(kernel._started_plugins, list)


# ── PluginBase shared mutable default ──


class TestPluginBaseSharedDefault:
    """P1: PluginBase subclasses must get their own dependencies list."""

    def test_subclass_isolation(self):
        from open_researcher.kernel.plugin import PluginBase

        class PluginA(PluginBase):
            name = "a"

        class PluginB(PluginBase):
            name = "b"

        a = PluginA()
        b = PluginB()
        a.dependencies.append("foo")
        assert "foo" not in b.dependencies


# ── file_ops atomic write ──


class TestFileOpsAtomicWrite:
    """P0: atomic_write_text must handle fsync errors gracefully."""

    def test_atomic_write_text(self, tmp_path):
        from open_researcher.plugins.storage.file_ops import atomic_write_text

        target = tmp_path / "test.txt"
        atomic_write_text(target, "hello world")
        assert target.read_text() == "hello world"

    def test_no_tmp_files_left(self, tmp_path):
        from open_researcher.plugins.storage.file_ops import atomic_write_text

        target = tmp_path / "test.txt"
        atomic_write_text(target, "content")
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []

    def test_atomic_write_json(self, tmp_path):
        from open_researcher.plugins.storage.file_ops import atomic_write_json

        target = tmp_path / "test.json"
        atomic_write_json(target, {"key": "value"})
        data = json.loads(target.read_text())
        assert data == {"key": "value"}


# ── EventJournal file lock ──


class TestEventJournalLocking:
    """P1: EventJournal must use file lock for concurrent access."""

    def test_has_lock(self, tmp_path):
        from open_researcher.event_journal import EventJournal

        journal = EventJournal(tmp_path / "events.jsonl")
        assert hasattr(journal, "_lock")

    def test_concurrent_emit(self, tmp_path):
        from open_researcher.event_journal import EventJournal

        journal = EventJournal(tmp_path / "events.jsonl")
        errors = []

        def emit_batch(start_id):
            for i in range(10):
                try:
                    journal.emit("info", "test", f"event_{start_id}_{i}")
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=emit_batch, args=(tid,)) for tid in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        records = journal.read_records()
        assert len(records) == 40  # 4 threads × 10 events


# ── Safety symlink traversal protection ──


class TestSafetySymlinkTraversal:
    """P0: _remove_path must refuse to traverse outside repo."""

    def test_refuses_path_outside_repo(self, tmp_path):
        from open_researcher.plugins.orchestrator.safety import (
            GitWorkspaceError,
            _remove_path,
        )

        repo = tmp_path / "repo"
        repo.mkdir()
        # Attempt to remove a path that resolves outside the repo
        with pytest.raises(GitWorkspaceError, match="outside repo"):
            _remove_path(repo, "../../etc/passwd")

    def test_allows_path_inside_repo(self, tmp_path):
        from open_researcher.plugins.orchestrator.safety import _remove_path

        repo = tmp_path / "repo"
        repo.mkdir()
        target = repo / "subdir" / "file.txt"
        target.parent.mkdir(parents=True)
        target.write_text("test")
        _remove_path(repo, "subdir/file.txt")
        assert not target.exists()


# ── Doctor cmd cfg guard ──


class TestDoctorCmdCfgGuard:
    """P1: run_doctor handles cfg=None at bootstrap resolution."""

    def test_cfg_none_guard(self):
        source = inspect.getsource(
            __import__("open_researcher.doctor_cmd", fromlist=["run_doctor"]).run_doctor
        )
        # cfg used conditionally: "if research.is_dir() and cfg is not None"
        assert "cfg is not None" in source


# ── Demo cmd subprocess safety ──


class TestDemoCmdSafety:
    """P1: demo_cmd subprocess calls should use list form."""

    def test_setup_demo_repo_uses_list_form(self):
        source = inspect.getsource(
            __import__("open_researcher.demo_cmd", fromlist=["_setup_demo_repo"])._setup_demo_repo
        )
        # Should use list form for git commands
        assert '["git"' in source
        # Should NOT use shell=True
        assert "shell=True" not in source


# ── Workspace paths normalization ──


class TestWorkspacePathsNormalization:
    """P1: normalize_relative_path handles edge cases."""

    def test_strips_leading_dotslash(self):
        from open_researcher.workspace_paths import normalize_relative_path

        assert normalize_relative_path("./foo/bar") == "foo/bar"
        assert normalize_relative_path("././foo") == "foo"

    def test_backslash_to_forward(self):
        from open_researcher.workspace_paths import normalize_relative_path

        assert normalize_relative_path("foo\\bar\\baz") == "foo/bar/baz"

    def test_empty_string(self):
        from open_researcher.workspace_paths import normalize_relative_path

        assert normalize_relative_path("") == ""
        assert normalize_relative_path("  ") == ""


# ── Memory policy safe priority ──


class TestMemoryPolicySafePriority:
    """P1: _safe_priority handles non-numeric values."""

    def test_none_returns_default(self):
        from open_researcher.memory_policy import _safe_priority

        assert _safe_priority(None) == 5

    def test_string_returns_default(self):
        from open_researcher.memory_policy import _safe_priority

        assert _safe_priority("bad") == 5

    def test_negative_clamped(self):
        from open_researcher.memory_policy import _safe_priority

        assert _safe_priority(-1) == 1
        assert _safe_priority(0) == 1

    def test_valid_int(self):
        from open_researcher.memory_policy import _safe_priority

        assert _safe_priority(3) == 3
        assert _safe_priority("7") == 7
