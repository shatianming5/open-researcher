import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def pool():
    from open_researcher.plugins.scheduler.idea_pool import IdeaPoolStore
    from open_researcher.plugins.storage.db import Database

    db = Database(":memory:")
    await db.open()
    store = IdeaPoolStore(db)
    yield store
    await db.close()


async def test_add_idea(pool):
    idea = await pool.add(title="Try larger batch size", priority=5)
    assert idea["id"].startswith("idea-")
    assert idea["status"] == "pending"


async def test_list_pending(pool):
    await pool.add(title="A", priority=3)
    await pool.add(title="B", priority=7)
    pending = await pool.list_by_status("pending")
    assert len(pending) == 2


async def test_claim_idea(pool):
    await pool.add(title="A", priority=5)
    claimed = await pool.claim(worker_id="w-1")
    assert claimed is not None
    assert claimed["status"] == "claimed"
    assert claimed["claimed_by"] == "w-1"
    second = await pool.claim(worker_id="w-2")
    assert second is None


async def test_complete_idea(pool):
    idea = await pool.add(title="A", priority=5)
    await pool.claim(worker_id="w-1")
    await pool.complete(idea["id"])
    result = await pool.get(idea["id"])
    assert result["status"] == "done"


async def test_claim_respects_priority(pool):
    await pool.add(title="Low", priority=1)
    await pool.add(title="High", priority=10)
    claimed = await pool.claim(worker_id="w-1")
    assert claimed["title"] == "High"


async def test_scheduler_plugin_lifecycle():
    """SchedulerPlugin creates an IdeaPoolStore from StoragePlugin's database."""
    from open_researcher.kernel import Kernel
    from open_researcher.plugins.scheduler import SchedulerPlugin
    from open_researcher.plugins.storage import StoragePlugin

    storage = StoragePlugin(db_path=":memory:")
    scheduler = SchedulerPlugin()

    k = Kernel(db_path=":memory:")
    await k.boot([storage, scheduler])

    assert scheduler.pool is not None
    idea = await scheduler.pool.add(title="Test idea", priority=5)
    assert idea["status"] == "pending"

    await k.shutdown()
    assert scheduler.pool is None
