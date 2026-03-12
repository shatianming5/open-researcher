"""Tests for timeout watchdog."""

import threading
import time

from paperfarm.watchdog import TimeoutWatchdog


def test_watchdog_fires_on_timeout():
    """Watchdog callback should fire after the timeout elapses."""
    event = threading.Event()

    def on_timeout():
        event.set()

    wd = TimeoutWatchdog(timeout_seconds=0.3, on_timeout=on_timeout)
    wd.start()
    # Wait enough time for timeout to fire
    assert event.wait(timeout=1.0), "Watchdog did not fire within expected time"


def test_watchdog_reset_prevents_timeout():
    """Resetting the watchdog should postpone the timeout."""
    event = threading.Event()

    def on_timeout():
        event.set()

    wd = TimeoutWatchdog(timeout_seconds=0.5, on_timeout=on_timeout)
    wd.start()
    # Reset before the original timeout would fire
    time.sleep(0.3)
    wd.reset()
    # Wait a bit more -- should NOT have fired yet (0.3s into new 0.5s timer)
    time.sleep(0.3)
    assert not event.is_set(), "Watchdog fired despite reset"
    # Clean up
    wd.stop()


def test_watchdog_stop():
    """Stopping the watchdog should prevent the callback from firing."""
    event = threading.Event()

    def on_timeout():
        event.set()

    wd = TimeoutWatchdog(timeout_seconds=0.3, on_timeout=on_timeout)
    wd.start()
    wd.stop()
    # Wait past the timeout
    time.sleep(0.5)
    assert not event.is_set(), "Watchdog fired after being stopped"
