"""Timeout watchdog -- kill agent if experiment exceeds time limit."""

import threading
from typing import Callable


class TimeoutWatchdog:
    """Resettable watchdog timer that fires a callback on timeout."""

    def __init__(self, timeout_seconds: int, on_timeout: Callable[[], None]):
        self.timeout = timeout_seconds
        self.on_timeout = on_timeout
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if self.timeout <= 0:
            return
        with self._lock:
            self._cancel_timer()
            self._timer = threading.Timer(self.timeout, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def reset(self) -> None:
        self.start()

    def stop(self) -> None:
        with self._lock:
            self._cancel_timer()

    def _fire(self) -> None:
        try:
            self.on_timeout()
        except Exception:
            pass

    def _cancel_timer(self) -> None:
        if self._timer:
            self._timer.cancel()
            self._timer = None
