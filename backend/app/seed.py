"""First-run seed: an offline demo channel, built-in Pollinations models.

Real providers are configured by the user in「模型与密钥」.  Seeding a demo
channel means the studio is explorable before any key is added; the built-in
Pollinations channel is usable as soon as a key is supplied via
``POLLINATIONS_API_KEY`` or the key editor.
"""

from __future__ import annotations

import os
import sqlite3

from . import crypto, db

POLLINATIONS_BASE_URL = "https://gen.pollinations.ai/v1"
POLLINATIONS_CHANNEL_NAME = "Pollinations"
POLLINATIONS_ENV_KEY = "POLLINATIONS_API_KEY"
POLLINATIONS_ENV_LABEL = "环境变量"
POLLINATIONS_SEED_VERSION = "1"
POLLINATIONS_DEFAULT_UPSTREAM = "black-forest-labs/flux.2-klein-4b"

# Fixed ids keep re-seeding idempotent; existing user-created rows are reused
# by (channel, upstream_model) instead of being duplicated.
POLLINATIONS_MODELS = [
    {
        "id": "builtin-pollinations-flux-schnell",
        "name": "Pollinations · Flux Schnell",
        "upstream": "black-forest-labs/flux.1-schnell",
        "description": "最快的纯文生图模型；按 Pollen 计费",
        "max_refs": 0,
        "features": ["seed", "negative"],
    },
    {
        "id": "builtin-pollinations-kontext",
        "name": "Pollinations · Kontext",
        "upstream": "black-forest-labs/flux.1-kontext-pro",
        "description": "单参考图编辑；适合改图与风格迁移",
        "max_refs": 1,
        "features": ["reference", "img2img", "seed", "negative"],
    },
    {
        "id": "builtin-pollinations-flux2-klein",
        "name": "Pollinations · Flux.2 Klein",
        "upstream": "black-forest-labs/flux.2-klein-4b",
        "description": "多参考图生成与编辑（最多 3 张）",
        "max_refs": 3,
        "features": ["reference", "img2img", "seed", "negative"],
    },
]


def seed_prompts(conn: sqlite3.Connection) -> None:
    """Built-in prompt fragments; fixed ids keep user edits/favorites intact."""

    snippets = [
        ("builtin-quality-detail", "超高清细节", "quality", "超高清，细节丰富，材质纹理真实，边缘干净", "低质量, 模糊, 噪点", "清晰 细节 质感"),
        ("builtin-quality-clean", "干净画面", "quality", "画面干净，构图简洁，主体突出，没有多余元素", "杂乱, 文字, 水印", "干净 简洁"),
        ("builtin-camera-portrait", "85mm 人像", "camera", "85mm 人像镜头，中景，浅景深，背景自然虚化", "", "人像 镜头 景深"),
        ("builtin-camera-wide", "广角环境", "camera", "24mm 广角镜头，低机位，环境纵深感强", "畸变", "广角 环境"),
        ("builtin-lighting-soft", "柔和侧光", "lighting", "柔和侧光，体积光，暖色阴影，层次自然", "", "光线 柔和 侧光"),
        ("builtin-lighting-neon", "霓虹夜景", "lighting", "雨夜霓虹，冷暖双色轮廓光，湿润地面反射，体积雾", "", "霓虹 夜景 赛博"),
        ("builtin-style-cinema", "电影剧照", "style", "电影剧照质感，低饱和，35mm 胶片颗粒，构图留白克制", "", "电影 胶片"),
        ("builtin-style-anime", "日系动画", "style", "日系动画赛璐璐上色，干净线稿，通透高光，柔和渐变天空", "", "动画 二次元"),
    ]
    stamp = db.now()
    for prompt_id, title, category, text, negative, tags in snippets:
        conn.execute(
            "INSERT OR IGNORE INTO prompts "
            "(id, title, category, text, negative, tags, favorite, builtin, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, 1, ?, ?)",
            (prompt_id, title, category, text, negative, tags, stamp, stamp),
        )


def seed_if_empty(conn: sqlite3.Connection) -> None:
    if db.scalar(conn, "SELECT COUNT(*) FROM channels"):
        return
    stamp = db.now()
    channel_id = db.new_id()
    conn.execute(
        "INSERT INTO channels(id, name, protocol, base_url, headers, enabled, note, created_at, updated_at) "
        "VALUES (?, ?, 'mock', '', '{}', 1, ?, ?, ?)",
        (
            channel_id,
            "离线演示",
            "不需要密钥，用来熟悉工作台；真实模型请在「模型与密钥」中接入。",
            stamp,
            stamp,
        ),
    )
    demos = [
        {
            "name": "演示 · 角色设定",
            "modality": "image",
            "upstream": "mock-image",
            "description": "离线占位图，验证参考图、批量与工作流",
            "caps": {"max_refs": 4, "max_count": 4, "features": ["reference", "seed", "negative"]},
            "params": {},
            "price": {"mode": "per_image", "amount": 0.0, "currency": "CNY"},
        },
        {
            "name": "演示 · 电影分镜",
            "modality": "image",
            "upstream": "mock-cinema",
            "description": "宽银幕比例占位图，用于演示批量出图",
            "caps": {"max_refs": 2, "max_count": 4, "features": ["reference", "seed"]},
            "params": {},
            "price": {"mode": "per_image", "amount": 0.0, "currency": "CNY"},
        },
        {
            "name": "演示 · 视频运镜",
            "modality": "video",
            "upstream": "mock-video",
            "description": "离线生成的 3 秒演示片段",
            "caps": {"max_refs": 1, "max_count": 1, "features": ["first_frame"]},
            "params": {"duration": [3, 5], "resolution": ["720p"]},
            "price": {"mode": "per_second", "amount": 0.0, "currency": "CNY"},
        },
    ]
    for demo in demos:
        conn.execute(
            "INSERT INTO models(id, name, modality, channel_id, upstream_model, description, enabled, "
            "caps, params, price, overrides, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, '{}', ?, ?)",
            (
                db.new_id(),
                demo["name"],
                demo["modality"],
                channel_id,
                demo["upstream"],
                demo["description"],
                db.dumps(demo["caps"]),
                db.dumps(demo["params"]),
                db.dumps(demo["price"]),
                stamp,
                stamp,
            ),
        )


def _find_pollinations_channel(conn: sqlite3.Connection) -> dict | None:
    return db.one(
        conn,
        "SELECT * FROM channels WHERE protocol = 'openai_image' AND base_url = ? "
        "ORDER BY created_at LIMIT 1",
        (POLLINATIONS_BASE_URL,),
    )


def _create_pollinations_channel(conn: sqlite3.Connection) -> dict:
    stamp = db.now()
    channel_id = "builtin-pollinations"
    if db.one(conn, "SELECT id FROM channels WHERE id = ?", (channel_id,)):
        channel_id = db.new_id()
    conn.execute(
        "INSERT INTO channels(id, name, protocol, base_url, headers, enabled, note, created_at, updated_at) "
        "VALUES (?, ?, 'openai_image', ?, '{}', 1, ?, ?, ?)",
        (
            channel_id,
            POLLINATIONS_CHANNEL_NAME,
            POLLINATIONS_BASE_URL,
            "内置 pollinations.ai 认证接口（OpenAI 兼容）；密钥可用环境变量或密钥页配置。",
            stamp,
            stamp,
        ),
    )
    return db.one(conn, "SELECT * FROM channels WHERE id = ?", (channel_id,))


def _ensure_pollinations_models(conn: sqlite3.Connection, channel_id: str) -> None:
    stamp = db.now()
    caps = {"max_count": 1, "sizes": [], "aspects": []}
    price = {"mode": "unconfigured", "amount": 0, "currency": "CNY"}
    for spec in POLLINATIONS_MODELS:
        existing = db.one(
            conn,
            "SELECT id FROM models WHERE channel_id = ? AND upstream_model = ? LIMIT 1",
            (channel_id, spec["upstream"]),
        )
        if existing:
            continue
        model_id = spec["id"]
        if db.one(conn, "SELECT id FROM models WHERE id = ?", (model_id,)):
            model_id = db.new_id()
        conn.execute(
            "INSERT INTO models(id, name, modality, channel_id, upstream_model, description, enabled, "
            "caps, params, price, overrides, created_at, updated_at) "
            "VALUES (?, ?, 'image', ?, ?, ?, 1, ?, '{}', ?, '{}', ?, ?)",
            (
                model_id,
                spec["name"],
                channel_id,
                spec["upstream"],
                spec["description"],
                db.dumps({**caps, "max_refs": spec["max_refs"], "features": spec["features"]}),
                db.dumps(price),
                stamp,
                stamp,
            ),
        )


def _sync_pollinations_env_key(conn: sqlite3.Connection, channel_id: str) -> None:
    secret = os.environ.get(POLLINATIONS_ENV_KEY, "").strip()
    if not secret:
        return
    keys = db.rows(
        conn,
        "SELECT id, label, secret FROM channel_keys WHERE channel_id = ? ORDER BY created_at",
        (channel_id,),
    )
    for key in keys:
        if crypto.decrypt(key["secret"]) == secret:
            return
    managed = next((key for key in keys if key["label"] == POLLINATIONS_ENV_LABEL), None)
    if managed:
        conn.execute(
            "UPDATE channel_keys SET secret = ?, enabled = 1, status = 'untested', "
            "cooldown_until = NULL, fail_count = 0, last_error = NULL WHERE id = ?",
            (crypto.encrypt(secret), managed["id"]),
        )
        return
    conn.execute(
        "INSERT INTO channel_keys(id, channel_id, label, secret, enabled, created_at) "
        "VALUES (?, ?, ?, ?, 1, ?)",
        (db.new_id(), channel_id, POLLINATIONS_ENV_LABEL, crypto.encrypt(secret), db.now()),
    )


def _ensure_pollinations_default(conn: sqlite3.Connection, channel_id: str) -> None:
    current = db.setting(conn, "default_image_model", "")
    if current and db.one(conn, "SELECT id FROM models WHERE id = ?", (current,)):
        return
    has_key = db.scalar(
        conn,
        "SELECT COUNT(*) FROM channel_keys WHERE channel_id = ? AND enabled = 1",
        (channel_id,),
    )
    if not has_key:
        return
    preferred = db.one(
        conn,
        "SELECT id FROM models WHERE channel_id = ? AND upstream_model = ? LIMIT 1",
        (channel_id, POLLINATIONS_DEFAULT_UPSTREAM),
    )
    if preferred:
        db.set_setting(conn, "default_image_model", preferred["id"])


def seed_pollinations(conn: sqlite3.Connection) -> None:
    """Idempotent built-in channel/models; env key is synced on every startup.

    The API key never lives in code: ``POLLINATIONS_API_KEY`` is copied into the
    encrypted local key pool (or the user enters it in「模型与密钥」).
    """

    channel = _find_pollinations_channel(conn)
    marker = db.scalar(
        conn, "SELECT v FROM app_meta WHERE k = 'builtin_pollinations_seed'"
    )
    if marker != POLLINATIONS_SEED_VERSION:
        if not channel:
            channel = _create_pollinations_channel(conn)
        _ensure_pollinations_models(conn, channel["id"])
        conn.execute(
            "INSERT INTO app_meta(k, v) VALUES ('builtin_pollinations_seed', ?) "
            "ON CONFLICT(k) DO UPDATE SET v = excluded.v",
            (POLLINATIONS_SEED_VERSION,),
        )
    if not channel:
        return
    _sync_pollinations_env_key(conn, channel["id"])
    _ensure_pollinations_default(conn, channel["id"])
