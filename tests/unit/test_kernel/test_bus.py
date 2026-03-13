"""Tests for the async EventBus."""
import asyncio
import pytest

pytestmark = pytest.mark.asyncio


async def test_emit_and_receive():
    from open_researcher.kernel.bus import EventBus
    from open_researcher.kernel.event import Event
    from open_researcher.kernel.store import EventStore

    store = EventStore(":memory:")
    await store.open()
    bus = EventBus(store)

    received = []
    bus.on("experiment.started", lambda e: received.append(e))

    await bus.emit(Event(type="experiment.started", payload={"id": 1}))
    await asyncio.sleep(0.05)

    assert len(received) == 1
    assert received[0].payload == {"id": 1}
    assert await store.count() == 1
    await store.close()


async def test_wildcard_subscription():
    from open_researcher.kernel.bus import EventBus
    from open_researcher.kernel.event import Event
    from open_researcher.kernel.store import EventStore

    store = EventStore(":memory:")
    await store.open()
    bus = EventBus(store)

    received = []
    bus.on("experiment.*", lambda e: received.append(e))

    await bus.emit(Event(type="experiment.started", payload={}))
    await bus.emit(Event(type="experiment.completed", payload={}))
    await bus.emit(Event(type="scout.completed", payload={}))
    await asyncio.sleep(0.05)

    assert len(received) == 2
    await store.close()


async def test_star_receives_all():
    from open_researcher.kernel.bus import EventBus
    from open_researcher.kernel.event import Event
    from open_researcher.kernel.store import EventStore

    store = EventStore(":memory:")
    await store.open()
    bus = EventBus(store)

    received = []
    bus.on("*", lambda e: received.append(e))

    await bus.emit(Event(type="a", payload={}))
    await bus.emit(Event(type="b.c", payload={}))
    await asyncio.sleep(0.05)

    assert len(received) == 2
    await store.close()


async def test_handler_error_does_not_crash_bus():
    from open_researcher.kernel.bus import EventBus
    from open_researcher.kernel.event import Event
    from open_researcher.kernel.store import EventStore

    store = EventStore(":memory:")
    await store.open()
    bus = EventBus(store)

    ok_received = []

    def bad_handler(e):
        raise RuntimeError("boom")

    bus.on("test", bad_handler)
    bus.on("test", lambda e: ok_received.append(e))

    await bus.emit(Event(type="test", payload={}))
    await asyncio.sleep(0.05)

    assert len(ok_received) == 1
    await store.close()


async def test_async_handler():
    from open_researcher.kernel.bus import EventBus
    from open_researcher.kernel.event import Event
    from open_researcher.kernel.store import EventStore

    store = EventStore(":memory:")
    await store.open()
    bus = EventBus(store)

    received = []

    async def async_handler(e):
        await asyncio.sleep(0.01)
        received.append(e)

    bus.on("test", async_handler)

    await bus.emit(Event(type="test", payload={"v": 1}))
    await asyncio.sleep(0.1)

    assert len(received) == 1
    assert received[0].payload == {"v": 1}
    await store.close()


async def test_off_removes_handler():
    from open_researcher.kernel.bus import EventBus
    from open_researcher.kernel.event import Event
    from open_researcher.kernel.store import EventStore

    store = EventStore(":memory:")
    await store.open()
    bus = EventBus(store)

    received = []
    handler = lambda e: received.append(e)
    bus.on("test", handler)
    bus.off("test", handler)

    await bus.emit(Event(type="test", payload={}))
    await asyncio.sleep(0.05)

    assert len(received) == 0
    await store.close()
