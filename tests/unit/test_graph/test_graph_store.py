import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def graph_store():
    from open_researcher.plugins.storage.db import Database
    from open_researcher.plugins.graph.store import GraphStore

    db = Database(":memory:")
    await db.open()
    store = GraphStore(db)
    yield store
    await db.close()


async def test_add_hypothesis(graph_store):
    h = await graph_store.add_hypothesis(
        id="h-001", claim="Larger batch size improves accuracy", status="proposed"
    )
    assert h["id"] == "h-001"
    assert h["status"] == "proposed"


async def test_get_hypothesis(graph_store):
    await graph_store.add_hypothesis(id="h-001", claim="Test", status="proposed")
    h = await graph_store.get_hypothesis("h-001")
    assert h is not None
    assert h["claim"] == "Test"


async def test_get_missing_hypothesis_returns_none(graph_store):
    h = await graph_store.get_hypothesis("nonexistent")
    assert h is None


async def test_update_hypothesis_status(graph_store):
    await graph_store.add_hypothesis(id="h-001", claim="Test", status="proposed")
    await graph_store.update_hypothesis("h-001", status="testing")
    h = await graph_store.get_hypothesis("h-001")
    assert h["status"] == "testing"


async def test_list_hypotheses(graph_store):
    await graph_store.add_hypothesis(id="h-001", claim="A", status="proposed")
    await graph_store.add_hypothesis(id="h-002", claim="B", status="testing")
    all_h = await graph_store.list_hypotheses()
    assert len(all_h) == 2
    proposed = await graph_store.list_hypotheses(status="proposed")
    assert len(proposed) == 1


async def test_add_and_list_evidence(graph_store):
    await graph_store.add_hypothesis(id="h-001", claim="Test", status="proposed")
    # Insert a matching experiment so the FK constraint is satisfied.
    graph_store._db.conn.execute(
        "INSERT INTO experiments (id, name, status) VALUES (1, 'exp-1', 'pending')"
    )
    graph_store._db.conn.commit()
    await graph_store.add_evidence(
        id="ev-001",
        hypothesis_id="h-001",
        experiment_id=1,
        direction="supports",
        summary="Accuracy improved by 5%",
    )
    evs = await graph_store.list_evidence(hypothesis_id="h-001")
    assert len(evs) == 1
    assert evs[0]["direction"] == "supports"
