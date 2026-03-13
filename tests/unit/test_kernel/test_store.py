"""Tests for SQLite-backed EventStore."""
import asyncio
import pytest

pytestmark = pytest.mark.asyncio


async def test_append_and_replay():
    from open_researcher.kernel.event import Event
    from open_researcher.kernel.store import EventStore

    store = EventStore(":memory:")
    await store.open()

    e1 = Event(type="a.one", payload={"x": 1}, source="p1")
    e2 = Event(type="b.two", payload={"y": 2}, source="p2")
    await store.append(e1)
    await store.append(e2)

    events = await store.replay()
    assert len(events) == 2
    assert events[0].type == "a.one"
    assert events[1].type == "b.two"
    await store.close()


async def test_replay_by_type():
    from open_researcher.kernel.event import Event
    from open_researcher.kernel.store import EventStore

    store = EventStore(":memory:")
    await store.open()

    await store.append(Event(type="experiment.started", payload={}))
    await store.append(Event(type="scout.completed", payload={}))
    await store.append(Event(type="experiment.completed", payload={}))

    events = await store.replay(type_prefix="experiment.")
    assert len(events) == 2
    assert all(e.type.startswith("experiment.") for e in events)
    await store.close()


async def test_replay_since_timestamp():
    from open_researcher.kernel.event import Event
    from open_researcher.kernel.store import EventStore
    import time

    store = EventStore(":memory:")
    await store.open()

    t_before = time.time() - 10
    await store.append(Event(type="old", payload={}, ts=t_before))
    t_mid = time.time()
    await store.append(Event(type="new", payload={}, ts=t_mid + 1))

    events = await store.replay(since=t_mid)
    assert len(events) == 1
    assert events[0].type == "new"
    await store.close()


async def test_replay_type_prefix_escapes_wildcards():
    """Ensure % and _ in type_prefix don't act as SQL LIKE wildcards."""
    from open_researcher.kernel.event import Event
    from open_researcher.kernel.store import EventStore

    store = EventStore(":memory:")
    await store.open()

    await store.append(Event(type="test%wild", payload={}))
    await store.append(Event(type="test_wild", payload={}))
    await store.append(Event(type="testXwild", payload={}))

    # Only exact prefix should match
    events = await store.replay(type_prefix="test%")
    assert len(events) == 1
    assert events[0].type == "test%wild"

    events = await store.replay(type_prefix="test_")
    assert len(events) == 1
    assert events[0].type == "test_wild"
    await store.close()


async def test_event_count():
    from open_researcher.kernel.event import Event
    from open_researcher.kernel.store import EventStore

    store = EventStore(":memory:")
    await store.open()
    assert await store.count() == 0

    await store.append(Event(type="a", payload={}))
    await store.append(Event(type="b", payload={}))
    assert await store.count() == 2
    await store.close()
