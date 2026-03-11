"""Tests for crash counter."""

from open_researcher.crash_counter import CrashCounter


def test_crash_counter_triggers_at_limit():
    """Counter should return True when consecutive crashes reach the limit."""
    cc = CrashCounter(max_crashes=3)
    assert cc.record("crash") is False  # 1st crash
    assert cc.record("crash") is False  # 2nd crash
    assert cc.record("crash") is True  # 3rd crash -- limit reached


def test_crash_counter_resets_on_success():
    """A non-crash status should reset the consecutive counter."""
    cc = CrashCounter(max_crashes=3)
    cc.record("crash")  # 1
    cc.record("crash")  # 2
    cc.record("success")  # resets
    assert cc.consecutive == 0
    # After reset, need 3 more crashes to trigger
    assert cc.record("crash") is False  # 1
    assert cc.record("crash") is False  # 2
    assert cc.record("crash") is True  # 3 -- limit reached


def test_crash_counter_reset_method():
    """The reset() method should clear the consecutive counter."""
    cc = CrashCounter(max_crashes=3)
    cc.record("crash")
    cc.record("crash")
    assert cc.consecutive == 2
    cc.reset()
    assert cc.consecutive == 0
