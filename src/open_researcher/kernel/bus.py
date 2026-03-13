"""Async event bus with wildcard subscriptions."""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Callable

from open_researcher.kernel.event import Event, event_matches
from open_researcher.kernel.store import EventStore

logger = logging.getLogger(__name__)

Handler = Callable[[Event], None]


class EventBus:
    """Async event bus: persist then dispatch."""

    def __init__(self, store: EventStore) -> None:
        self._store = store
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def on(self, pattern: str, handler: Handler) -> None:
        self._handlers[pattern].append(handler)

    def off(self, pattern: str, handler: Handler) -> None:
        try:
            self._handlers[pattern].remove(handler)
        except ValueError:
            pass

    async def emit(self, event: Event) -> None:
        await self._store.append(event)
        asyncio.get_running_loop().call_soon(self._dispatch_sync, event)

    def _dispatch_sync(self, event: Event) -> None:
        for pattern, handlers in self._handlers.items():
            if event_matches(event, pattern):
                for handler in handlers:
                    try:
                        handler(event)
                    except Exception:
                        logger.exception(
                            "Handler %r failed for event %s", handler, event.type
                        )
