"""ViewModel — projects kernel events into TUI-friendly state.

The ViewModel subscribes to all events (``*``) and maintains a snapshot
of the research session state that the Textual app can read.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from open_researcher.kernel.event import Event


@dataclass
class SessionSnapshot:
    """Current snapshot of the research session for rendering."""
    phase: str = "idle"
    cycle: int = 0
    experiments_completed: int = 0
    experiments_failed: int = 0
    hypotheses_count: int = 0
    last_event_type: str = ""
    last_event_ts: float = 0.0
    is_running: bool = False
    errors: list[str] = field(default_factory=list)


class ViewModel:
    """Maintains a live snapshot of the session state by processing events."""

    def __init__(self) -> None:
        self._snapshot = SessionSnapshot()

    @property
    def snapshot(self) -> SessionSnapshot:
        return self._snapshot

    def on_event(self, event: Event) -> None:
        """Process a kernel event and update the snapshot."""
        self._snapshot.last_event_type = event.type
        self._snapshot.last_event_ts = event.ts

        # Update phase based on event type prefixes
        if event.type.startswith("scout."):
            self._snapshot.phase = "scouting"
            self._snapshot.is_running = True
        elif event.type.startswith("manager."):
            self._snapshot.phase = "managing"
            self._snapshot.is_running = True
            if "cycle" in event.payload:
                self._snapshot.cycle = event.payload["cycle"]
        elif event.type.startswith("critic."):
            self._snapshot.phase = "reviewing"
        elif event.type.startswith("experiment."):
            self._snapshot.phase = "experimenting"
            if event.type == "experiment.completed":
                exit_code = event.payload.get("exit_code", -1)
                if exit_code == 0:
                    self._snapshot.experiments_completed += 1
                else:
                    self._snapshot.experiments_failed += 1
        elif event.type == "run.completed" or event.type == "run.stopped":
            self._snapshot.phase = "idle"
            self._snapshot.is_running = False
