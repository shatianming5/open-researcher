import pytest

pytestmark = pytest.mark.asyncio


async def test_db_open_and_close():
    from open_researcher.plugins.storage.db import Database

    db = Database(":memory:")
    await db.open()
    assert db.conn is not None
    await db.close()


async def test_db_insert_and_query():
    from open_researcher.plugins.storage.db import Database

    db = Database(":memory:")
    await db.open()
    db.conn.execute(
        "INSERT INTO ideas (id, title, status, priority, created_at) VALUES (?, ?, ?, ?, ?)",
        ("idea-1", "Test", "pending", 5.0, 1000.0),
    )
    db.conn.commit()
    row = db.conn.execute(
        "SELECT title FROM ideas WHERE id = ?", ("idea-1",)
    ).fetchone()
    assert row[0] == "Test"
    await db.close()


async def test_storage_plugin_lifecycle():
    from open_researcher.kernel.kernel import Kernel
    from open_researcher.plugins.storage import StoragePlugin

    plugin = StoragePlugin(db_path=":memory:")
    k = Kernel(db_path=":memory:")
    await k.boot([plugin])
    assert plugin.db.conn is not None
    tables = {
        row[0]
        for row in plugin.db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "experiments" in tables
    assert "ideas" in tables
    await k.shutdown()
