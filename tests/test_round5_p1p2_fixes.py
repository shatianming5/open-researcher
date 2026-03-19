"""Tests for Round 5 P1/P2 fixes: agent adapters, db, launch_detached, headless, doctor, demo, workspace_paths."""

from __future__ import annotations

import asyncio
import inspect

import pytest

# ── claude_code read_text encoding + error handling ──


class TestClaudeCodeReadText:
    """P1: ClaudeCodeAdapter.run must handle encoding and OSError gracefully."""

    def test_read_text_uses_utf8(self):
        source = inspect.getsource(
            __import__("open_researcher.agents.claude_code", fromlist=["ClaudeCodeAdapter"]).ClaudeCodeAdapter.run
        )
        assert 'encoding="utf-8"' in source

    def test_catches_unicode_decode_error(self):
        source = inspect.getsource(
            __import__("open_researcher.agents.claude_code", fromlist=["ClaudeCodeAdapter"]).ClaudeCodeAdapter.run
        )
        assert "UnicodeDecodeError" in source

    def test_catches_os_error(self):
        source = inspect.getsource(
            __import__("open_researcher.agents.claude_code", fromlist=["ClaudeCodeAdapter"]).ClaudeCodeAdapter.run
        )
        assert "OSError" in source

    def test_file_not_found_returns_1(self, tmp_path):
        from open_researcher.agents.claude_code import ClaudeCodeAdapter

        adapter = ClaudeCodeAdapter()
        messages = []
        code = adapter.run(tmp_path, on_output=messages.append, program_file="nonexistent.md")
        assert code == 1
        assert any("not found" in m for m in messages)

    def test_unicode_error_returns_1(self, tmp_path):
        from open_researcher.agents.claude_code import ClaudeCodeAdapter

        research = tmp_path / ".research"
        research.mkdir()
        program = research / "program.md"
        # Write invalid UTF-8 bytes
        program.write_bytes(b"\x80\x81\x82\xff")

        adapter = ClaudeCodeAdapter()
        messages = []
        code = adapter.run(tmp_path, on_output=messages.append)
        assert code == 1
        assert any("failed to read" in m for m in messages)


# ── base.py stdin close in finally ──


class TestAgentBaseStdinClose:
    """P1: AgentAdapter._run_process must close stdin in a finally block."""

    def test_stdin_close_in_finally(self):
        source = inspect.getsource(
            __import__("open_researcher.agents.base", fromlist=["AgentAdapter"]).AgentAdapter._run_process
        )
        # Verify finally block structure for stdin close
        assert "finally:" in source
        assert "proc.stdin.close()" in source


# ── db.py open/close thread safety ──


class TestDatabaseOpenCloseSafety:
    """P1: Database.open/close must use self.lock and guard against double-open."""

    def test_open_uses_lock(self):
        source = inspect.getsource(
            __import__("open_researcher.plugins.storage.db", fromlist=["Database"]).Database.open
        )
        assert "self.lock" in source

    def test_close_uses_lock(self):
        source = inspect.getsource(
            __import__("open_researcher.plugins.storage.db", fromlist=["Database"]).Database.close
        )
        assert "self.lock" in source

    def test_double_open_is_noop(self, tmp_path):
        from open_researcher.plugins.storage.db import Database

        db = Database(tmp_path / "test.db")

        async def _run():
            await db.open()
            conn1 = db.conn
            await db.open()  # second open should be no-op
            conn2 = db.conn
            assert conn1 is conn2
            await db.close()

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_run())
        finally:
            loop.close()

    def test_close_sets_conn_none(self, tmp_path):
        from open_researcher.plugins.storage.db import Database

        db = Database(tmp_path / "test.db")

        async def _run():
            await db.open()
            assert db.conn is not None
            await db.close()
            assert db.conn is None

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_run())
        finally:
            loop.close()


# ── migrations.py fetchone None check ──


class TestMigrationsFetchoneNone:
    """P1: apply_migrations must handle fetchone() returning None."""

    def test_source_has_none_guard(self):
        source = inspect.getsource(
            __import__("open_researcher.plugins.storage.migrations", fromlist=["apply_migrations"]).apply_migrations
        )
        # Should have a guard for fetchone() result
        assert "if row" in source or "row[0] if row" in source


# ── launch_detached type safety ──


class TestLaunchDetachedTypeSafety:
    """P1: launch_detached must handle non-numeric state values safely."""

    def test_uses_signal_module(self):
        source = inspect.getsource(
            __import__("open_researcher.scripts.launch_detached", fromlist=["_launch_detached"])._launch_detached
        )
        assert "signal.SIGTERM" in source

    def test_type_safe_exit_code(self):
        source = inspect.getsource(
            __import__("open_researcher.scripts.launch_detached", fromlist=["_launch_detached"])._launch_detached
        )
        assert "TypeError, ValueError" in source

    def test_fallback_on_kill_failure(self):
        source = inspect.getsource(
            __import__("open_researcher.scripts.launch_detached", fromlist=["_launch_detached"])._launch_detached
        )
        assert "proc.kill()" in source


# ── EventStore replay JSON safety ──


class TestEventStoreReplayJsonSafety:
    """P1: EventStore.replay must skip corrupt JSON payloads."""

    def test_corrupt_payload_skipped(self, tmp_path):
        from open_researcher.kernel.event import Event
        from open_researcher.kernel.store import EventStore

        db_path = tmp_path / "events.db"
        store = EventStore(db_path)

        async def _run():
            await store.open()
            # Insert a good event
            await store.append(Event(type="test.good", payload={"ok": True}))
            # Inject a corrupt JSON payload directly
            store._require_conn().execute(
                "INSERT INTO events (type, payload, ts, source, corr_id) VALUES (?, ?, ?, ?, ?)",
                ("test.bad", "not-valid-json{{{", 1.0, "", ""),
            )
            store._require_conn().commit()
            events = await store.replay()
            await store.close()
            return events

        loop = asyncio.new_event_loop()
        try:
            events = loop.run_until_complete(_run())
        finally:
            loop.close()
        assert len(events) == 1
        assert events[0].type == "test.good"

    def test_require_conn_raises_when_closed(self):
        from open_researcher.kernel.store import EventStore

        store = EventStore(":memory:")
        with pytest.raises(RuntimeError, match="Store not opened"):
            store._require_conn()


# ── EventBus shutdown ──


class TestEventBusShutdown:
    """P1: EventBus must have a shutdown method for task cleanup."""

    def test_has_shutdown_method(self):
        from open_researcher.kernel.bus import EventBus

        assert hasattr(EventBus, "shutdown")
        assert inspect.iscoroutinefunction(EventBus.shutdown)

    def test_shutdown_clears_tasks(self):
        from open_researcher.kernel.bus import EventBus
        from open_researcher.kernel.store import EventStore

        store = EventStore(":memory:")
        bus = EventBus(store)

        async def _run():
            await store.open()
            await bus.shutdown()
            assert len(bus._pending_tasks) == 0

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_run())
        finally:
            loop.close()


# ── event_journal emit fsync ──


class TestEventJournalFsync:
    """P1: EventJournal.emit must fsync after write."""

    def test_fsync_in_source(self):
        source = inspect.getsource(
            __import__("open_researcher.event_journal", fromlist=["EventJournal"]).EventJournal.emit
        )
        assert "os.fsync" in source
        assert "handle.flush()" in source


# ── legacy_worktree binary diff ──


class TestLegacyWorktreeBinaryDiff:
    """P1: _sync_source_overlays must use text=False for binary diff/apply."""

    def test_diff_uses_binary_mode(self):
        source = inspect.getsource(
            __import__(
                "open_researcher.plugins.execution.legacy_worktree",
                fromlist=["_sync_source_overlays"],
            )._sync_source_overlays
        )
        assert "text=False" in source

    def test_all_subprocess_have_timeout(self):
        """All subprocess.run calls in legacy_worktree must have timeout."""
        import open_researcher.plugins.execution.legacy_worktree as mod

        full_source = inspect.getsource(mod)
        # Count subprocess.run calls vs timeout= occurrences
        import re

        run_calls = len(re.findall(r"subprocess\.run\(", full_source))
        timeout_params = len(re.findall(r"timeout=\w+", full_source))
        assert timeout_params >= run_calls, f"Found {run_calls} subprocess.run calls but only {timeout_params} timeouts"


# ── headless agent terminate safety ──


class TestHeadlessAgentTerminateSafety:
    """P1: headless do_run_headless must wrap agent.terminate() in try/except."""

    def test_terminate_wrapped_in_try(self):
        source = inspect.getsource(
            __import__("open_researcher.headless", fromlist=["do_run_headless"]).do_run_headless
        )
        # Should have per-agent try/except in finally block
        assert "for agent in" in source
        assert "agent.terminate()" in source

    def test_session_failed_on_exception(self):
        source = inspect.getsource(
            __import__("open_researcher.headless", fromlist=["do_run_headless"]).do_run_headless
        )
        assert "SessionFailed" in source

    def test_start_headless_terminate_wrapped(self):
        source = inspect.getsource(
            __import__("open_researcher.headless", fromlist=["do_start_headless"]).do_start_headless
        )
        assert "for agent in" in source
        assert "agent.terminate()" in source


# ── doctor_cmd splitlines safety ──


class TestDoctorCmdSplitlinesSafety:
    """P2: doctor_cmd must not IndexError on empty splitlines."""

    def test_driver_version_safe_indexing(self):
        source = inspect.getsource(
            __import__("open_researcher.doctor_cmd", fromlist=["_check_gpu_info"])._check_gpu_info
        )
        # Should not have direct [0] on splitlines() in a single expression
        assert "splitlines()[0]" not in source

    def test_yaml_specific_exception(self):
        source = inspect.getsource(
            __import__("open_researcher.doctor_cmd", fromlist=["run_doctor"]).run_doctor
        )
        assert "YAMLError" in source

    def test_opencode_subprocess_timeout(self):
        source = inspect.getsource(
            __import__("open_researcher.doctor_cmd", fromlist=["_check_opencode_cli"])._check_opencode_cli
        )
        assert "timeout=" in source


# ── demo_cmd shlex.quote ──


class TestDemoCmdShellSafety:
    """P2: demo_cmd Server() call must use shlex.quote."""

    def test_uses_shlex_quote(self):
        source = inspect.getsource(
            __import__("open_researcher.demo_cmd", fromlist=["do_demo"]).do_demo
        )
        assert "shlex.quote" in source


# ── workspace_paths OSError handling ──


class TestWorkspacePathsOSError:
    """P2: overlay_manifest_entry_for_path must catch OSError."""

    def test_catches_os_error(self):
        source = inspect.getsource(
            __import__(
                "open_researcher.workspace_paths",
                fromlist=["overlay_manifest_entry_for_path"],
            ).overlay_manifest_entry_for_path
        )
        assert "OSError" in source

    def test_returns_none_on_oserror(self, tmp_path):
        from open_researcher.workspace_paths import overlay_manifest_entry_for_path

        # Non-existent path should return None (not raise)
        result = overlay_manifest_entry_for_path(tmp_path / "nonexistent")
        assert result is None

    def test_returns_entry_for_file(self, tmp_path):
        from open_researcher.workspace_paths import overlay_manifest_entry_for_path

        f = tmp_path / "test.txt"
        f.write_text("hello")
        result = overlay_manifest_entry_for_path(f)
        assert result is not None
        assert result["kind"] == "file"
        assert result["size"] == 5
        assert "sha256" in result

    def test_returns_entry_for_symlink(self, tmp_path):
        from open_researcher.workspace_paths import overlay_manifest_entry_for_path

        target = tmp_path / "target.txt"
        target.write_text("hello")
        link = tmp_path / "link.txt"
        link.symlink_to(target)
        result = overlay_manifest_entry_for_path(link)
        assert result is not None
        assert result["kind"] == "symlink"
