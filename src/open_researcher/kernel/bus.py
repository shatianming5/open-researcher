"""Async event bus with wildcard subscriptions."""
from __future__ import annotations

import asyncio
import inspect
import logging
from collections import defaultdict
from typing import Callable, Union

from open_researcher.kernel.event import Event, event_matches
from open_researcher.kernel.store import EventStore

logger = logging.getLogger(__name__)

Handler = Union[Callable[[Event], None], Callable[[Event], "asyncio.Future[None]"]]


class EventBus:
    """Async event bus: persist then dispatch.

    Handlers may be sync or async callables.  Sync handlers are invoked via
    ``call_soon``; async handlers are scheduled as tasks.
    """

    def __init__(self, store: EventStore) -> None:
        self._store = store
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._pending_tasks: set[asyncio.Task] = set()

    def on(self, pattern: str, handler: Handler) -> None:
        self._handlers[pattern].append(handler)

    def off(self, pattern: str, handler: Handler) -> None:
        try:
            self._handlers[pattern].remove(handler)
        except ValueError:
            pass

    async def emit(self, event: Event) -> None:
        await self._store.append(event)
        loop = asyncio.get_running_loop()
        loop.call_soon(self._dispatch, event, loop)

    def _dispatch(self, event: Event, loop: asyncio.AbstractEventLoop) -> None:
        for pattern, handlers in self._handlers.items():
            if event_matches(event, pattern):
                for handler in handlers:
                    try:
                        if inspect.iscoroutinefunction(handler):
                            task = loop.create_task(self._safe_async_call(handler, event))
                            self._pending_tasks.add(task)
                            task.add_done_callback(self._pending_tasks.discard)
                        else:
                            handler(event)
                    except Exception:
                        logger.exception(
                            "Handler %r failed for event %s", handler, event.type
                        )

    async def shutdown(self) -> None:
        """Cancel and await all pending handler tasks."""
        for task in list(self._pending_tasks):
            task.cancel()
        if self._pending_tasks:
            await asyncio.gather(*self._pending_tasks, return_exceptions=True)
        self._pending_tasks.clear()

    @staticmethod
    async def _safe_async_call(handler: Callable, event: Event) -> None:
        try:
            await handler(event)
        except Exception:
            logger.exception(
                "Async handler %r failed for event %s", handler, event.type
            )
