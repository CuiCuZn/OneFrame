"""SQLite persistence layer (WAL, foreign keys, small typed helpers)."""

from __future__ import annotations

import contextlib
import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS app_meta (
  k TEXT PRIMARY KEY,
  v TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS channels (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  protocol TEXT NOT NULL,
  base_url TEXT NOT NULL DEFAULT '',
  headers TEXT NOT NULL DEFAULT '{}',
  enabled INTEGER NOT NULL DEFAULT 1,
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS channel_keys (
  id TEXT PRIMARY KEY,
  channel_id TEXT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
  label TEXT NOT NULL DEFAULT '',
  secret TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'untested',
  cooldown_until TEXT,
  fail_count INTEGER NOT NULL DEFAULT 0,
  ok_count INTEGER NOT NULL DEFAULT 0,
  last_used_at TEXT,
  last_error TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_keys_channel ON channel_keys(channel_id);

CREATE TABLE IF NOT EXISTS models (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  modality TEXT NOT NULL,
  channel_id TEXT NOT NULL DEFAULT '',
  upstream_model TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  enabled INTEGER NOT NULL DEFAULT 1,
  caps TEXT NOT NULL DEFAULT '{}',
  params TEXT NOT NULL DEFAULT '{}',
  price TEXT NOT NULL DEFAULT '{}',
  overrides TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  model_id TEXT,
  model_name TEXT NOT NULL DEFAULT '',
  channel_name TEXT NOT NULL DEFAULT '',
  modality TEXT NOT NULL DEFAULT 'image',
  request TEXT NOT NULL,
  status TEXT NOT NULL,
  stage TEXT NOT NULL DEFAULT '',
  progress REAL NOT NULL DEFAULT 0,
  route_id TEXT,
  channel_id TEXT,
  key_id TEXT,
  upstream_job_id TEXT,
  attempts TEXT NOT NULL DEFAULT '[]',
  error TEXT,
  price REAL NOT NULL DEFAULT 0,
  currency TEXT NOT NULL DEFAULT 'USD',
  external_url TEXT,
  canceled INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC);

CREATE TABLE IF NOT EXISTS assets (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  path TEXT,
  thumb_path TEXT,
  poster_path TEXT,
  width INTEGER,
  height INTEGER,
  duration_ms INTEGER,
  bytes INTEGER,
  job_id TEXT,
  prompt TEXT NOT NULL DEFAULT '',
  negative TEXT NOT NULL DEFAULT '',
  model_id TEXT,
  model_name TEXT NOT NULL DEFAULT '',
  channel_name TEXT NOT NULL DEFAULT '',
  params TEXT NOT NULL DEFAULT '{}',
  favorite INTEGER NOT NULL DEFAULT 0,
  tags TEXT NOT NULL DEFAULT '',
  origin TEXT NOT NULL DEFAULT 'generated',
  meta TEXT NOT NULL DEFAULT '{}',
  parent_id TEXT,
  root_id TEXT,
  tool TEXT NOT NULL DEFAULT '',
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assets_created ON assets(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_assets_job ON assets(job_id);

CREATE TABLE IF NOT EXISTS library_items (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL DEFAULT 'folder',
  external_id TEXT,
  kind TEXT NOT NULL DEFAULT 'other',
  title TEXT NOT NULL DEFAULT '',
  subtitle TEXT NOT NULL DEFAULT '',
  category TEXT NOT NULL DEFAULT '',
  category_path TEXT NOT NULL DEFAULT '',
  tags TEXT NOT NULL DEFAULT '',
  search_text TEXT NOT NULL DEFAULT '',
  image_path TEXT NOT NULL,
  thumb_path TEXT,
  depth_path TEXT,
  depth_thumb_path TEXT,
  has_depth INTEGER NOT NULL DEFAULT 0,
  group_key TEXT NOT NULL DEFAULT '',
  variant_label TEXT NOT NULL DEFAULT '',
  width INTEGER,
  height INTEGER,
  favorite INTEGER NOT NULL DEFAULT 0,
  nsfw INTEGER NOT NULL DEFAULT 0,
  meta TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_library_kind ON library_items(kind, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_library_external ON library_items(source, external_id);

-- One row per (item, dimension, value): the multi-level classification that
-- powers the reference library's category tree and facet chips.
CREATE TABLE IF NOT EXISTS library_facets (
  item_id TEXT NOT NULL REFERENCES library_items(id) ON DELETE CASCADE,
  field TEXT NOT NULL,
  value TEXT NOT NULL,
  level INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (item_id, field, value)
);
CREATE INDEX IF NOT EXISTS idx_library_facets_value ON library_facets(field, value);
CREATE INDEX IF NOT EXISTS idx_library_facets_item ON library_facets(item_id);

CREATE TABLE IF NOT EXISTS settings (
  k TEXT PRIMARY KEY,
  v TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prompts (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT 'custom',
  text TEXT NOT NULL,
  negative TEXT NOT NULL DEFAULT '',
  tags TEXT NOT NULL DEFAULT '',
  favorite INTEGER NOT NULL DEFAULT 0,
  builtin INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_prompts_category ON prompts(category, favorite, created_at DESC);
"""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex


@contextlib.contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    config.ensure_dirs()
    conn = sqlite3.connect(config.DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=8000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]


def _backup_v1(conn: sqlite3.Connection, source: Path) -> None:
    _backup_copy(conn, source, ".v1.bak")


def _backup_copy(conn: sqlite3.Connection, source: Path, suffix: str) -> None:
    if not source.exists():
        return
    target = source.with_name(source.name + suffix)
    if target.exists():
        return
    conn.commit()
    dest = sqlite3.connect(target)
    try:
        conn.backup(dest, pages=64)
    finally:
        dest.close()


def _migrate_models_v2(conn: sqlite3.Connection, source: Path | None = None) -> int:
    """v1 used ``models`` + ``routes``; v2 binds one model to one channel/model.

    Existing multi-route models are split into independent models so that every
    (vendor, model) pair becomes its own selectable entry.  The original database
    is copied next to the live one before any change.
    """

    if "channel_id" in _table_columns(conn, "models"):
        conn.execute("DROP TABLE IF EXISTS routes")
        return 0

    _backup_v1(conn, source or config.DB_PATH)
    conn.execute("ALTER TABLE models ADD COLUMN channel_id TEXT NOT NULL DEFAULT ''")
    conn.execute("ALTER TABLE models ADD COLUMN upstream_model TEXT NOT NULL DEFAULT ''")
    conn.execute("ALTER TABLE models ADD COLUMN overrides TEXT NOT NULL DEFAULT '{}'")

    tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "routes" not in tables:
        return 0

    created = 0
    models = rows(conn, "SELECT * FROM models")
    for model in models:
        routes = rows(
            conn,
            """
            SELECT r.*, c.name AS channel_name
            FROM routes r LEFT JOIN channels c ON c.id = r.channel_id
            WHERE r.model_id = ?
            ORDER BY r.priority DESC, r.weight DESC
            """,
            (model["id"],),
        )
        if not routes:
            continue
        primary = routes[0]
        conn.execute(
            "UPDATE models SET channel_id=?, upstream_model=?, overrides=? WHERE id=?",
            (
                primary["channel_id"],
                primary["upstream_model"],
                primary["overrides"] or "{}",
                model["id"],
            ),
        )
        for extra in routes[1:]:
            suffix = extra.get("channel_name") or "线路"
            conn.execute(
                """
                INSERT INTO models
                  (id, name, modality, channel_id, upstream_model, description, enabled,
                   caps, params, price, overrides, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id(),
                    f"{model['name']} · {suffix}",
                    model["modality"],
                    extra["channel_id"],
                    extra["upstream_model"],
                    model["description"],
                    int(bool(model["enabled"]) and bool(extra["enabled"])),
                    model["caps"],
                    model["params"],
                    model["price"],
                    extra["overrides"] or "{}",
                    now(),
                    now(),
                ),
            )
            created += 1
    conn.execute("DROP TABLE IF EXISTS routes")
    return created


def _migrate_library_v3(conn: sqlite3.Connection) -> None:
    """v3 adds category paths, a search blob and the facet table.

    Existing rows are reclassified from their source JSON (or from their filenames)
    once, by ``core.library.ensure_taxonomy`` right after startup.
    """

    columns = _table_columns(conn, "library_items")
    if "category_path" not in columns:
        conn.execute("ALTER TABLE library_items ADD COLUMN category_path TEXT NOT NULL DEFAULT ''")
    if "search_text" not in columns:
        conn.execute("ALTER TABLE library_items ADD COLUMN search_text TEXT NOT NULL DEFAULT ''")
    if "nsfw" not in columns:
        conn.execute("ALTER TABLE library_items ADD COLUMN nsfw INTEGER NOT NULL DEFAULT 0")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_library_path ON library_items(category_path)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_library_nsfw ON library_items(nsfw, kind)")


def _migrate_jobs_v5(conn: sqlite3.Connection) -> None:
    job_columns = _table_columns(conn, "jobs")
    if "channel_name" not in job_columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN channel_name TEXT NOT NULL DEFAULT ''")

    conn.execute(
        """
        UPDATE jobs
        SET channel_name = (
            SELECT name FROM channels WHERE channels.id = jobs.channel_id
        )
        WHERE (channel_name IS NULL OR channel_name = '')
          AND channel_id IS NOT NULL AND channel_id != ''
          AND EXISTS (SELECT 1 FROM channels WHERE channels.id = jobs.channel_id)
        """
    )
    conn.execute(
        """
        UPDATE jobs
        SET channel_name = (
            SELECT c.name FROM models m
            JOIN channels c ON c.id = m.channel_id
            WHERE m.id = jobs.model_id
        )
        WHERE (channel_name IS NULL OR channel_name = '')
          AND model_id IS NOT NULL AND model_id != ''
          AND EXISTS (SELECT 1 FROM models m JOIN channels c ON c.id = m.channel_id WHERE m.id = jobs.model_id)
        """
    )
    empty_rows = rows(conn, "SELECT id, request FROM jobs WHERE channel_name IS NULL OR channel_name = ''")
    for r in empty_rows:
        req = loads(r.get("request"), {})
        cname = req.get("channel_name")
        if cname:
            conn.execute("UPDATE jobs SET channel_name = ? WHERE id = ?", (cname, r["id"]))


def _migrate_v6(conn: sqlite3.Connection, source: Path | None = None) -> None:
    """v6 adds reference variants/depth, asset lineage and the prompt library."""

    asset_columns = set(_table_columns(conn, "assets"))
    library_columns = set(_table_columns(conn, "library_items"))
    asset_fields = {"parent_id", "root_id", "tool", "version"}
    library_fields = {"group_key", "variant_label", "depth_path", "depth_thumb_path", "has_depth"}
    if asset_fields <= asset_columns and library_fields <= library_columns:
        return

    _backup_copy(conn, source or config.DB_PATH, ".v5.bak")
    for column, ddl in (
        ("parent_id", "ALTER TABLE assets ADD COLUMN parent_id TEXT"),
        ("root_id", "ALTER TABLE assets ADD COLUMN root_id TEXT"),
        ("tool", "ALTER TABLE assets ADD COLUMN tool TEXT NOT NULL DEFAULT ''"),
        ("version", "ALTER TABLE assets ADD COLUMN version INTEGER NOT NULL DEFAULT 1"),
    ):
        if column not in asset_columns:
            conn.execute(ddl)
    for column, ddl in (
        ("group_key", "ALTER TABLE library_items ADD COLUMN group_key TEXT NOT NULL DEFAULT ''"),
        ("variant_label", "ALTER TABLE library_items ADD COLUMN variant_label TEXT NOT NULL DEFAULT ''"),
        ("depth_path", "ALTER TABLE library_items ADD COLUMN depth_path TEXT"),
        ("depth_thumb_path", "ALTER TABLE library_items ADD COLUMN depth_thumb_path TEXT"),
        ("has_depth", "ALTER TABLE library_items ADD COLUMN has_depth INTEGER NOT NULL DEFAULT 0"),
    ):
        if column not in library_columns:
            conn.execute(ddl)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_assets_root ON assets(root_id, version)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_assets_parent ON assets(parent_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_library_group ON library_items(group_key)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_library_depth ON library_items(has_depth, kind)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS prompts (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          category TEXT NOT NULL DEFAULT 'custom',
          text TEXT NOT NULL,
          negative TEXT NOT NULL DEFAULT '',
          tags TEXT NOT NULL DEFAULT '',
          favorite INTEGER NOT NULL DEFAULT 0,
          builtin INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_prompts_category ON prompts(category, favorite, created_at DESC)"
    )
    conn.execute("UPDATE assets SET root_id = id WHERE root_id IS NULL OR root_id = ''")
    conn.execute("UPDATE assets SET version = 1 WHERE version IS NULL OR version < 1")


def init_db() -> None:
    config.ensure_dirs()
    with connect() as conn:
        conn.executescript(SCHEMA)
        for key, value in config.DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings(k, v) VALUES (?, ?)", (key, value)
            )
        _migrate_models_v2(conn)
        _migrate_library_v3(conn)
        _migrate_jobs_v5(conn)
        _migrate_v6(conn)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_models_channel ON models(channel_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_assets_root ON assets(root_id, version)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_assets_parent ON assets(parent_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_library_group ON library_items(group_key)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_library_depth ON library_items(has_depth, kind)")
        conn.execute(
            "INSERT INTO app_meta(k, v) VALUES ('schema_version', '6') "
            "ON CONFLICT(k) DO UPDATE SET v = excluded.v"
        )


def rows(conn: sqlite3.Connection, sql: str, args: tuple | list = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def one(conn: sqlite3.Connection, sql: str, args: tuple | list = ()) -> dict | None:
    row = conn.execute(sql, args).fetchone()
    return dict(row) if row else None


def scalar(conn: sqlite3.Connection, sql: str, args: tuple | list = ()) -> Any:
    row = conn.execute(sql, args).fetchone()
    return row[0] if row else None


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def loads(value: str | None, fallback: Any = None) -> Any:
    if not value:
        return {} if fallback is None else fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {} if fallback is None else fallback


def settings_all(conn: sqlite3.Connection) -> dict[str, str]:
    data = {r["k"]: r["v"] for r in rows(conn, "SELECT k, v FROM settings")}
    return {**config.DEFAULT_SETTINGS, **data}


def setting(conn: sqlite3.Connection, key: str, fallback: str = "") -> str:
    row = one(conn, "SELECT v FROM settings WHERE k = ?", (key,))
    return row["v"] if row else config.DEFAULT_SETTINGS.get(key, fallback)


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings(k, v) VALUES (?, ?) "
        "ON CONFLICT(k) DO UPDATE SET v = excluded.v",
        (key, str(value)),
    )


def touch(path: Path) -> str:
    """Relative POSIX path used in URLs/DB when the file lives under data/."""
    try:
        return path.resolve().relative_to(config.DATA_DIR).as_posix()
    except ValueError:
        return str(path.resolve())
