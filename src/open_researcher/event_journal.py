"""Shared JSONL event journal for research and control events."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock

from open_researcher.kernel.events import (
    ResearchEvent,
    event_level,
    event_name,
    event_payload,
    event_phase,
)


def now_iso() -> str:
    """Return the standard UTC timestamp used in JSONL event logs."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _coerce_seq(record: dict) -> int | None:
    raw = record.get("seq")
    try:
        seq = int(raw)
    except (TypeError, ValueError):
        return None
    return seq if seq > 0 else None


def next_seq_unlocked(path: Path) -> int:
    """Compute the next global event sequence under an external file lock."""
    if not path.exists():
        return 1
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 1
    for line in reversed(lines):
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(record, dict):
            continue
        seq = _coerce_seq(record)
        if seq is not None:
            return seq + 1
    return 1


class EventJournal:
    """Append and read structured JSONL events with file locking."""

    def __init__(self, path: Path, stream=None):
        self.path = path
        self._stream = stream
        self._lock = FileLock(str(path) + ".lock")

    def emit(self, level: str, phase: str, event: str, **kwargs) -> dict:
        """Write one structured event record."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            seq = self._next_seq_unlocked()
            record = {
                "seq": seq,
                "ts": now_iso(),
                "level": level,
                "phase": phase,
                "event": event,
                **kwargs,
            }
            line = json.dumps(record, ensure_ascii=False)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            if self._stream is not None:
                self._stream.write(line + "\n")
                self._stream.flush()
        return record

    def _next_seq_unlocked(self) -> int:
        return next_seq_unlocked(self.path)

    def emit_typed(self, event: ResearchEvent) -> dict:
        """Write a typed research event using the standard mapping."""
        return self.emit(
            event_level(event),
            event_phase(event),
            event_name(event),
            **event_payload(event),
        )

    def read_records(self) -> list[dict]:
        """Read all well-formed JSONL records from the journal."""
        if not self.path.exists():
            return []
        with self._lock:
            lines = self.path.read_text(encoding="utf-8").splitlines()

        records: list[dict] = []
        for line in lines:
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(record, dict):
                records.append(record)
        return records

    def close(self) -> None:
        """Compatibility no-op for existing logger lifecycle hooks."""
        return None


def stdout_journal(path: Path) -> EventJournal:
    """Create a journal that mirrors events to stdout."""
    return EventJournal(path, stream=sys.stdout)
