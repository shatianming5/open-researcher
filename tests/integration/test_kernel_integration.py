"""Integration tests -- multiple plugins cooperating through the kernel."""
import asyncio

import pytest

pytestmark = pytest.mark.asyncio


async def test_full_kernel_boot_with_plugins():
    """All core plugins boot, communicate via events, and shutdown cleanly."""
    from open_researcher.kernel import Event, Kernel
    from open_researcher.plugins.agents import AgentsPlugin
    from open_researcher.plugins.storage import StoragePlugin

    storage = StoragePlugin(db_path=":memory:")
    agents = AgentsPlugin()

    k = Kernel(db_path=":memory:")
    await k.boot([storage, agents])

    await k.bus.emit(Event(type="test.ping", payload={"msg": "hello"}, source="test"))
    events = await k.store.replay()
    assert any(e.type == "test.ping" for e in events)

    tables = {
        row[0]
        for row in storage.db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "experiments" in tables
    assert "ideas" in tables
    assert "hypotheses" in tables

    await k.shutdown()


async def test_event_flow_between_plugins():
    """Verify events emitted by one plugin are received by another."""
    from open_researcher.kernel import Event, Kernel, PluginBase

    received_events = []

    class ProducerPlugin(PluginBase):
        name = "producer"
        dependencies: list[str] = []

        async def start(self, kernel):
            self._kernel = kernel

        async def produce(self):
            await self._kernel.bus.emit(
                Event(type="data.ready", payload={"rows": 42}, source=self.name)
            )

    class ConsumerPlugin(PluginBase):
        name = "consumer"
        dependencies = ["producer"]

        async def start(self, kernel):
            kernel.bus.on("data.*", lambda e: received_events.append(e))

    producer = ProducerPlugin()
    consumer = ConsumerPlugin()
    k = Kernel(db_path=":memory:")
    await k.boot([consumer, producer])

    await producer.produce()
    await asyncio.sleep(0.05)

    assert len(received_events) == 1
    assert received_events[0].payload["rows"] == 42
    await k.shutdown()


async def test_graph_store_with_storage_plugin():
    """GraphStore uses the StoragePlugin's database."""
    from open_researcher.kernel import Kernel
    from open_researcher.plugins.graph.store import GraphStore
    from open_researcher.plugins.storage import StoragePlugin

    storage = StoragePlugin(db_path=":memory:")
    k = Kernel(db_path=":memory:")
    await k.boot([storage])

    graph = GraphStore(storage.db)
    await graph.add_hypothesis(id="h-1", claim="Test", status="proposed")
    h = await graph.get_hypothesis("h-1")
    assert h["claim"] == "Test"
    await k.shutdown()


async def test_idea_pool_with_storage_plugin():
    """IdeaPoolStore uses the StoragePlugin's database."""
    from open_researcher.kernel import Kernel
    from open_researcher.plugins.scheduler.idea_pool import IdeaPoolStore
    from open_researcher.plugins.storage import StoragePlugin

    storage = StoragePlugin(db_path=":memory:")
    k = Kernel(db_path=":memory:")
    await k.boot([storage])

    pool = IdeaPoolStore(storage.db)
    idea = await pool.add(title="Test idea", priority=5)
    claimed = await pool.claim(worker_id="w-1")
    assert claimed["id"] == idea["id"]
    await k.shutdown()
