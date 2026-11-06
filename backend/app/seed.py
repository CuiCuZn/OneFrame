"""First-run seed: an offline demo channel and three demo models.

Real providers are configured by the user in「模型与密钥」.  Seeding a demo
channel means the studio is explorable before any key is added.
"""

from __future__ import annotations

import sqlite3

from . import db


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
