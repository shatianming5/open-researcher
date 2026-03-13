"""Tests for the orchestrator safety module."""
import threading

import pytest

pytestmark = pytest.mark.asyncio


def test_crash_counter_tracks_consecutive_crashes():
    from open_researcher.plugins.orchestrator.safety import CrashCounter

    cc = CrashCounter(max_crashes=3)
    assert cc.record("crash") is False  # 1
    assert cc.record("crash") is False  # 2
    assert cc.record("crash") is True   # 3 -> limit reached


def test_crash_counter_resets_on_success():
    from open_researcher.plugins.orchestrator.safety import CrashCounter

    cc = CrashCounter(max_crashes=3)
    cc.record("crash")
    cc.record("crash")
    cc.record("keep")  # success resets counter
    assert cc.record("crash") is False  # back to 1
    assert cc.record("crash") is False  # 2
    assert cc.record("crash") is True   # 3


def test_crash_counter_reset():
    from open_researcher.plugins.orchestrator.safety import CrashCounter

    cc = CrashCounter(max_crashes=2)
    cc.record("crash")
    cc.reset()
    assert cc.record("crash") is False  # 1 after reset


def test_crash_counter_is_thread_safe():
    from open_researcher.plugins.orchestrator.safety import CrashCounter

    cc = CrashCounter(max_crashes=1000)
    results: list[bool] = []

    def record_many():
        for _ in range(100):
            results.append(cc.record("crash"))

    threads = [threading.Thread(target=record_many) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All 500 should have been recorded
    assert cc.consecutive == 500
