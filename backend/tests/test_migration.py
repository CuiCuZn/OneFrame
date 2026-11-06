from __future__ import annotations

import sqlite3
from pathlib import Path

from app import db


def _v1_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE channels (
          id TEXT PRIMARY KEY, name TEXT, protocol TEXT, base_url TEXT, headers TEXT,
          enabled INTEGER, note TEXT, created_at TEXT, updated_at TEXT
        );
        CREATE TABLE models (
          id TEXT PRIMARY KEY, name TEXT, modality TEXT, description TEXT, enabled INTEGER,
          caps TEXT, params TEXT, price TEXT, created_at TEXT, updated_at TEXT
        );
        CREATE TABLE routes (
          id TEXT PRIMARY KEY, model_id TEXT, channel_id TEXT, upstream_model TEXT,
          priority INTEGER, weight INTEGER, enabled INTEGER, overrides TEXT
        );
        """
    )
    now = db.now()
    conn.execute(
        "INSERT INTO channels VALUES ('a', 'A厂', 'openai_image', 'https://a/v1', '{}', 1, '', ?, ?)",
        (now, now),
    )
    conn.execute(
        "INSERT INTO channels VALUES ('c', 'C厂', 'openai_image', 'https://c/v1', '{}', 1, '', ?, ?)",
        (now, now),
    )
    conn.execute(
        "INSERT INTO models VALUES ('m', 'a 模型', 'image', '', 1, '{}', '{}', '{}', ?, ?)",
        (now, now),
    )
    conn.execute("INSERT INTO routes VALUES ('r1', 'm', 'a', 'a-1', 200, 100, 1, '{}')")
    conn.execute("INSERT INTO routes VALUES ('r2', 'm', 'c', 'a-1', 100, 100, 1, '{}')")
    conn.commit()


def test_v1_routes_become_independent_models(tmp_path: Path):
    source = tmp_path / "v1.db"
    conn = sqlite3.connect(source)
    conn.row_factory = sqlite3.Row
    _v1_schema(conn)

    created = db._migrate_models_v2(conn, source)  # noqa: SLF001
    conn.commit()

    assert created == 1
    models = db.rows(conn, "SELECT * FROM models ORDER BY channel_id")
    assert len(models) == 2
    pairs = {(model["channel_id"], model["upstream_model"]) for model in models}
    assert pairs == {("a", "a-1"), ("c", "a-1")}
    assert any(model["name"].endswith("C厂") for model in models)
    tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "routes" not in tables
    conn.close()

    # The v1 database is preserved next to the migrated file.
    assert (tmp_path / "v1.db.v1.bak").exists()
    backup = sqlite3.connect(tmp_path / "v1.db.v1.bak")
    tables = {row[0] for row in backup.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "routes" in tables
    backup.close()
