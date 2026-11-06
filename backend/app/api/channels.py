"""Channel + key management endpoints."""

from __future__ import annotations

import sqlite3

import httpx
from fastapi import APIRouter, Depends

from .. import crypto, db
from ..errors import Conflict, NotFound
from ..providers import PROTOCOL_DOCS, catalog as protocol_catalog
from .deps import get_conn
from .schemas import ChannelIn, KeyIn

router = APIRouter(prefix="/api/channels", tags=["channels"])


def serialize_key(row: dict) -> dict:
    secret = crypto.decrypt(row["secret"])
    return {
        "id": row["id"],
        "label": row["label"],
        "masked": crypto.mask(secret),
        "enabled": bool(row["enabled"]),
        "status": row["status"],
        "cooldown_until": row["cooldown_until"],
        "fail_count": row["fail_count"],
        "ok_count": row["ok_count"],
        "last_used_at": row["last_used_at"],
        "last_error": row["last_error"],
        "created_at": row["created_at"],
    }


def serialize_channel(conn: sqlite3.Connection, row: dict, with_keys: bool = True) -> dict:
    keys = db.rows(
        conn,
        "SELECT * FROM channel_keys WHERE channel_id = ? ORDER BY created_at",
        (row["id"],),
    )
    models = db.scalar(conn, "SELECT COUNT(*) FROM models WHERE channel_id = ?", (row["id"],))
    data = {
        "id": row["id"],
        "name": row["name"],
        "protocol": row["protocol"],
        "protocol_label": PROTOCOL_DOCS.get(row["protocol"], {}).get("label")
        or next((p["label"] for p in protocol_catalog() if p["id"] == row["protocol"]), row["protocol"]),
        "base_url": row["base_url"],
        "headers": db.loads(row["headers"], {}),
        "note": row["note"],
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "key_count": len(keys),
        "healthy_keys": sum(1 for key in keys if key["enabled"] and key["status"] == "ok"),
        "keys": [serialize_key(key) for key in keys] if with_keys else [],
        "models_count": int(models or 0),
    }
    return data


def _channel_or_404(conn: sqlite3.Connection, channel_id: str) -> dict:
    row = db.one(conn, "SELECT * FROM channels WHERE id = ?", (channel_id,))
    if not row:
        raise NotFound("渠道不存在")
    return row


@router.get("")
def list_channels(conn: sqlite3.Connection = Depends(get_conn)):
    rows = db.rows(conn, "SELECT * FROM channels ORDER BY created_at")
    return [serialize_channel(conn, row) for row in rows]


@router.post("")
def create_channel(data: ChannelIn, conn: sqlite3.Connection = Depends(get_conn)):
    known = {item["id"] for item in protocol_catalog()}
    if data.protocol not in known:
        raise Conflict("未知协议")
    channel_id = db.new_id()
    stamp = db.now()
    conn.execute(
        "INSERT INTO channels(id, name, protocol, base_url, headers, enabled, note, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            channel_id,
            data.name.strip(),
            data.protocol,
            data.base_url,
            db.dumps(data.headers),
            int(data.enabled),
            data.note,
            stamp,
            stamp,
        ),
    )
    for key in data.keys:
        _add_key(conn, channel_id, key)
    return serialize_channel(conn, _channel_or_404(conn, channel_id))


@router.put("/{channel_id}")
def update_channel(
    channel_id: str, data: ChannelIn, conn: sqlite3.Connection = Depends(get_conn)
):
    _channel_or_404(conn, channel_id)
    conn.execute(
        "UPDATE channels SET name=?, protocol=?, base_url=?, headers=?, enabled=?, note=?, updated_at=? WHERE id=?",
        (
            data.name.strip(),
            data.protocol,
            data.base_url,
            db.dumps(data.headers),
            int(data.enabled),
            data.note,
            db.now(),
            channel_id,
        ),
    )
    return serialize_channel(conn, _channel_or_404(conn, channel_id))


@router.delete("/{channel_id}")
def delete_channel(channel_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    _channel_or_404(conn, channel_id)
    conn.execute("DELETE FROM models WHERE channel_id = ?", (channel_id,))
    conn.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
    return {"ok": True}


def _add_key(conn: sqlite3.Connection, channel_id: str, data: KeyIn) -> str:
    key_id = db.new_id()
    conn.execute(
        "INSERT INTO channel_keys(id, channel_id, label, secret, enabled, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            key_id,
            channel_id,
            data.label or f"密钥 {conn.execute('SELECT COUNT(*) FROM channel_keys WHERE channel_id=?', (channel_id,)).fetchone()[0] + 1}",
            crypto.encrypt(data.secret.strip()),
            int(data.enabled),
            db.now(),
        ),
    )
    return key_id


@router.post("/{channel_id}/keys")
def add_key(channel_id: str, data: KeyIn, conn: sqlite3.Connection = Depends(get_conn)):
    _channel_or_404(conn, channel_id)
    key_id = _add_key(conn, channel_id, data)
    row = db.one(conn, "SELECT * FROM channel_keys WHERE id = ?", (key_id,))
    return serialize_key(row)


@router.put("/{channel_id}/keys/{key_id}")
def update_key(
    channel_id: str, key_id: str, data: KeyIn, conn: sqlite3.Connection = Depends(get_conn)
):
    row = db.one(
        conn, "SELECT * FROM channel_keys WHERE id = ? AND channel_id = ?", (key_id, channel_id)
    )
    if not row:
        raise NotFound("密钥不存在")
    if data.secret.startswith("•") or not data.secret.strip():
        conn.execute(
            "UPDATE channel_keys SET label=?, enabled=? WHERE id=?",
            (data.label, int(data.enabled), key_id),
        )
    else:
        conn.execute(
            "UPDATE channel_keys SET label=?, secret=?, enabled=?, status='untested', "
            "cooldown_until=NULL, last_error=NULL WHERE id=?",
            (data.label, crypto.encrypt(data.secret.strip()), int(data.enabled), key_id),
        )
    return serialize_key(db.one(conn, "SELECT * FROM channel_keys WHERE id = ?", (key_id,)))


@router.delete("/{channel_id}/keys/{key_id}")
def delete_key(channel_id: str, key_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    conn.execute(
        "DELETE FROM channel_keys WHERE id = ? AND channel_id = ?", (key_id, channel_id)
    )
    return {"ok": True}


@router.post("/{channel_id}/keys/{key_id}/reset")
def reset_key(channel_id: str, key_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    conn.execute(
        "UPDATE channel_keys SET status='untested', cooldown_until=NULL, fail_count=0, last_error=NULL "
        "WHERE id=? AND channel_id=?",
        (key_id, channel_id),
    )
    return serialize_key(db.one(conn, "SELECT * FROM channel_keys WHERE id = ?", (key_id,)))


async def _probe(conn: sqlite3.Connection, row: dict, secret: str) -> dict:
    if row["protocol"] == "mock":
        return {"ok": True, "models": ["mock-image", "mock-video"], "message": "离线演示渠道无需连接"}
    base = row["base_url"].rstrip("/")
    if not base:
        return {"ok": False, "models": [], "message": "请先填写服务地址"}
    headers = db.loads(row["headers"], {})
    if row["protocol"].startswith("gemini"):
        headers["x-goog-api-key"] = secret
        url = f"{base}/models"
    else:
        headers["Authorization"] = f"Bearer {secret}"
        url = f"{base}/models"
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        return {"ok": False, "models": [], "message": f"连接失败：{type(exc).__name__}"}
    if resp.status_code >= 400:
        text = (resp.text or "")[:200]
        return {"ok": False, "models": [], "message": f"HTTP {resp.status_code}：{text}"}
    try:
        payload = resp.json()
    except ValueError:
        return {"ok": True, "models": [], "message": "地址可访问，但返回的不是模型列表"}
    items = payload.get("data") or payload.get("models") or []
    models = []
    for item in items:
        if isinstance(item, str):
            models.append(item)
        elif isinstance(item, dict):
            name = item.get("id") or item.get("name", "")
            models.append(name.removeprefix("models/"))
    return {"ok": True, "models": models, "message": f"连接成功，读到 {len(models)} 个模型"}


@router.post("/{channel_id}/test")
async def test_channel(
    channel_id: str,
    key_id: str | None = None,
    conn: sqlite3.Connection = Depends(get_conn),
):
    row = _channel_or_404(conn, channel_id)
    keys = db.rows(conn, "SELECT * FROM channel_keys WHERE channel_id = ? AND enabled = 1", (channel_id,))
    if key_id:
        keys = [key for key in keys if key["id"] == key_id]
    if not keys and row["protocol"] != "mock":
        raise Conflict("该渠道还没有启用中的密钥")
    result = await _probe(conn, row, crypto.decrypt(keys[0]["secret"]) if keys else "")
    if keys:
        conn.execute(
            "UPDATE channel_keys SET status=?, last_error=? WHERE id=?",
            ("ok" if result["ok"] else "error", None if result["ok"] else result["message"][:300], keys[0]["id"]),
        )
    return result


@router.post("/{channel_id}/discover")
async def discover_models(
    channel_id: str, conn: sqlite3.Connection = Depends(get_conn)
):
    row = _channel_or_404(conn, channel_id)
    key = db.one(conn, "SELECT * FROM channel_keys WHERE channel_id=? AND enabled=1", (channel_id,))
    secret = crypto.decrypt(key["secret"]) if key else ""
    result = await _probe(conn, row, secret)
    return {"models": result["models"], "message": result["message"], "ok": result["ok"]}
