"""Phase gate -- pause for human review in collaborative mode."""

import json
from pathlib import Path

from paperfarm.control_plane import issue_control_command


class PhaseGate:
    def __init__(self, research_dir: Path, mode: str = "autonomous"):
        self.research_dir = research_dir
        self.mode = mode
        self._last_phase = self._read_phase()

    def _read_phase(self) -> str:
        path = self.research_dir / "experiment_progress.json"
        if not path.exists():
            return "init"
        try:
            return json.loads(path.read_text()).get("phase", "init")
        except (json.JSONDecodeError, OSError):
            return "init"

    def check(self) -> str | None:
        """Check for phase transition. Returns new phase if paused, else None."""
        current = self._read_phase()
        if current != self._last_phase:
            self._last_phase = current
            if self.mode == "collaborative":
                self._pause(current)
                return current
        return None

    def _pause(self, phase: str) -> None:
        reason = f"Phase completed: {phase}"
        issue_control_command(
            self.research_dir / "control.json",
            command="pause",
            source="phase_gate",
            reason=reason,
        )
