"""DDL for the Open Researcher state database (schema v1)."""

SCHEMA_V1 = """\
CREATE TABLE IF NOT EXISTS experiments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'pending',
    hypothesis  TEXT,
    metrics     TEXT,
    started_at  REAL,
    finished_at REAL,
    worker_id   TEXT,
    metadata    TEXT
);
CREATE TABLE IF NOT EXISTS hypotheses (
    id          TEXT PRIMARY KEY,
    claim       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'proposed',
    parent_id   TEXT,
    created_at  REAL,
    metadata    TEXT
);
CREATE TABLE IF NOT EXISTS evidence (
    id            TEXT PRIMARY KEY,
    hypothesis_id TEXT REFERENCES hypotheses(id),
    experiment_id INTEGER REFERENCES experiments(id),
    direction     TEXT,
    summary       TEXT,
    created_at    REAL
);
CREATE TABLE IF NOT EXISTS ideas (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    priority    REAL DEFAULT 0,
    claimed_by  TEXT,
    created_at  REAL,
    metadata    TEXT
);
CREATE TABLE IF NOT EXISTS memory (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at REAL
);
CREATE TABLE IF NOT EXISTS config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS control_commands (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    command TEXT NOT NULL,
    source  TEXT,
    reason  TEXT,
    ts      REAL
);
CREATE TABLE IF NOT EXISTS gpu_snapshots (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    data TEXT NOT NULL,
    ts   REAL
);
CREATE TABLE IF NOT EXISTS bootstrap_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    ts    REAL
);
"""
