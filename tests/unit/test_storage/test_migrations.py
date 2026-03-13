import sqlite3


def test_apply_creates_all_tables():
    from open_researcher.plugins.storage.migrations import apply_migrations

    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    expected = {
        "experiments",
        "hypotheses",
        "evidence",
        "ideas",
        "memory",
        "config",
        "control_commands",
        "gpu_snapshots",
        "bootstrap_state",
    }
    assert expected.issubset(tables)
    conn.close()


def test_apply_is_idempotent():
    from open_researcher.plugins.storage.migrations import apply_migrations

    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    apply_migrations(conn)  # no error
    conn.close()


def test_schema_version_is_set():
    from open_researcher.plugins.storage.migrations import apply_migrations

    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version >= 1
    conn.close()
