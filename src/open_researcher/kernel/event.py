"""Core Event dataclass — the single message type in the system."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any


@dataclass(frozen=True, slots=True)
class Event:
    """Universal event carried by the EventBus."""

    type: str
    payload: dict[str, Any]
    ts: float = field(default_factory=time.time)
    source: str = ""
    correlation_id: str = ""


def event_matches(event: Event, pattern: str) -> bool:
    """Check whether *event.type* matches a glob *pattern*."""
    return fnmatch(event.type, pattern)
