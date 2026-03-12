"""Crash counter -- pause experiments after N consecutive crashes."""

import threading


class CrashCounter:
    def __init__(self, max_crashes: int = 3):
        self.max_crashes = max_crashes
        self.consecutive = 0
        self._lock = threading.Lock()

    def record(self, status: str) -> bool:
        """Record result. Returns True if crash limit reached."""
        with self._lock:
            if status == "crash":
                self.consecutive += 1
                return self.consecutive >= self.max_crashes
            self.consecutive = 0
            return False

    def reset(self) -> None:
        with self._lock:
            self.consecutive = 0
