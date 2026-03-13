"""Adapter to bridge research_events callbacks to the kernel EventBus."""
from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any, Callable

from open_researcher.kernel.event import Event


def make_bus_emitter(bus: Any) -> Callable:
    """Return a sync callback compatible with ResearchLoop.emit that
    forwards events to the kernel EventBus.

    The callback is synchronous (ResearchLoop is sync) but schedules
    the async bus.emit via the running event loop.
    """

    def emit_callback(event: Any) -> None:
        # Convert research_events dataclass to kernel Event
        event_type = _event_type_name(event)
        try:
            payload = asdict(event)
        except TypeError:
            payload = {"raw": str(event)}

        kernel_event = Event(
            type=event_type,
            payload=payload,
            source="orchestrator",
        )

        # Schedule async emit on the running loop
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(bus.emit(kernel_event))
        except RuntimeError:
            # No running loop -- skip (happens in tests without async context)
            pass

    return emit_callback


def _event_type_name(event: Any) -> str:
    """Convert a research_events class name to a dotted event type string.

    e.g. ScoutStarted -> scout.started
         ExperimentCompleted -> experiment.completed
         ManagerCycleStarted -> manager.cycle_started
    """
    name = type(event).__name__
    # Insert dots before uppercase letters, then lowercase
    parts: list[str] = []
    current: list[str] = []
    for ch in name:
        if ch.isupper() and current:
            parts.append("".join(current))
            current = [ch.lower()]
        else:
            current.append(ch.lower())
    if current:
        parts.append("".join(current))

    if len(parts) >= 2:
        return f"{parts[0]}.{'_'.join(parts[1:])}"
    return parts[0] if parts else "unknown"
