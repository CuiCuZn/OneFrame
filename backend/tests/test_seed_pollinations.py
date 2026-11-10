from __future__ import annotations

import sqlite3

from app import crypto, db
from app.seed import (
    POLLINATIONS_BASE_URL,
    POLLINATIONS_DEFAULT_UPSTREAM,
    POLLINATIONS_MODELS,
    seed_if_empty,
    seed_pollinations,
)


def _conn(tmp_path) -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_path / "seed.db")
    conn.row_factory = sqlite3.Row
    conn.executescript(db.SCHEMA)
    conn.execute("INSERT OR IGNORE INTO settings(k, v) VALUES ('default_image_model', '')")
    return conn


def test_seed_pollinations_is_idempotent_and_syncs_env_key(tmp_path, monkeypatch):
    monkeypatch.setenv("POLLINATIONS_API_KEY", "sk-test-seed")
    conn = _conn(tmp_path)
    seed_if_empty(conn)
    seed_pollinations(conn)
    seed_pollinations(conn)

    channels = db.rows(
        conn, "SELECT * FROM channels WHERE base_url = ?", (POLLINATIONS_BASE_URL,)
    )
    assert len(channels) == 1
    channel_id = channels[0]["id"]
    models = db.rows(conn, "SELECT * FROM models WHERE channel_id = ?", (channel_id,))
    assert {model["upstream_model"] for model in models} == {
        spec["upstream"] for spec in POLLINATIONS_MODELS
    }
    keys = db.rows(
        conn, "SELECT * FROM channel_keys WHERE channel_id = ?", (channel_id,)
    )
    assert len(keys) == 1
    assert crypto.decrypt(keys[0]["secret"]) == "sk-test-seed"

    preferred = next(
        model
        for model in models
        if model["upstream_model"] == POLLINATIONS_DEFAULT_UPSTREAM
    )
    assert db.setting(conn, "default_image_model", "") == preferred["id"]
    conn.close()


def test_seed_pollinations_without_key_keeps_demo_default(tmp_path, monkeypatch):
    monkeypatch.delenv("POLLINATIONS_API_KEY", raising=False)
    conn = _conn(tmp_path)
    seed_if_empty(conn)
    seed_pollinations(conn)

    assert db.scalar(
        conn,
        "SELECT COUNT(*) FROM channels WHERE base_url = ?",
        (POLLINATIONS_BASE_URL,),
    ) == 1
    assert db.setting(conn, "default_image_model", "") == ""
    assert db.scalar(conn, "SELECT COUNT(*) FROM channel_keys") == 0
    conn.close()


def test_seed_pollinations_reuses_existing_channel_and_models(tmp_path, monkeypatch):
    monkeypatch.delenv("POLLINATIONS_API_KEY", raising=False)
    conn = _conn(tmp_path)
    stamp = db.now()
    conn.execute(
        "INSERT INTO channels(id, name, protocol, base_url, headers, enabled, note, created_at, updated_at) "
        "VALUES ('manual', 'My Pollinations', 'openai_image', ?, '{}', 1, '', ?, ?)",
        (POLLINATIONS_BASE_URL, stamp, stamp),
    )
    conn.execute(
        "INSERT INTO models(id, name, modality, channel_id, upstream_model, description, enabled, "
        "caps, params, price, overrides, created_at, updated_at) "
        "VALUES ('manual-model', 'manual', 'image', 'manual', ?, '', 1, '{}', '{}', '{}', '{}', ?, ?)",
        (POLLINATIONS_DEFAULT_UPSTREAM, stamp, stamp),
    )

    seed_pollinations(conn)

    assert db.scalar(conn, "SELECT COUNT(*) FROM channels") == 1
    assert db.scalar(
        conn, "SELECT COUNT(*) FROM models WHERE channel_id = 'manual'"
    ) == len(POLLINATIONS_MODELS)
    assert db.one(conn, "SELECT id FROM models WHERE id = 'manual-model'")
    assert db.setting(conn, "default_image_model", "") == ""
    conn.close()
