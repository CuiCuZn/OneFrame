"""Creative models: every (vendor, upstream model) pair is its own entry."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from .. import db
from ..core import router as routing
from ..errors import Conflict, NotFound
from ..providers import get_adapter
from .deps import get_conn
from .schemas import ModelIn

router = APIRouter(prefix="/api/models", tags=["models"])


def serialize(conn: sqlite3.Connection, row: dict) -> dict:
    model = routing.load_model(conn, row["id"])
    return {
        "id": model["id"],
        "name": model["name"],
        "modality": model["modality"],
        "channel_id": model["channel_id"],
        "channel_name": model.get("channel_name") or "",
        "protocol": model.get("protocol") or "",
        "upstream_model": model["upstream_model"],
        "description": model["description"],
        "enabled": bool(model["enabled"]),
        "caps": model["caps"],
        "params": model["params"],
        "price": model["price"],
        "overrides": model["overrides"],
        "available": model["available"],
        "reason": model["reason"],
        "created_at": model["created_at"],
        "updated_at": model["updated_at"],
    }


def _get(conn: sqlite3.Connection, model_id: str) -> dict:
    row = db.one(conn, "SELECT * FROM models WHERE id = ?", (model_id,))
    if not row:
        raise NotFound("模型不存在")
    return row


def _normalized_params(data: ModelIn) -> dict:
    params = dict(data.params)
    params.pop("size", None)
    if data.modality == "image":
        params.pop("aspect_ratio", None)
        params.pop("resolution", None)
    return params


def _validate(conn: sqlite3.Connection, data: ModelIn) -> None:
    channel = db.one(conn, "SELECT * FROM channels WHERE id = ?", (data.channel_id,))
    if not channel:
        raise NotFound("所选服务渠道不存在")
    try:
        adapter = get_adapter(channel["protocol"])
    except KeyError:
        raise Conflict("渠道协议未知") from None
    if data.modality not in adapter.modalities:
        raise Conflict(f"{adapter.label} 不支持{data.modality}类型")
    if data.caps.max_refs and not adapter.supports_reference:
        raise Conflict(f"{adapter.label} 不支持参考图，请把参考图上限设为 0")


@router.get("")
def list_models(conn: sqlite3.Connection = Depends(get_conn)):
    rows = db.rows(conn, "SELECT * FROM models ORDER BY created_at")
    return [serialize(conn, row) for row in rows]


@router.get("/{model_id}")
def get_model(model_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    return serialize(conn, _get(conn, model_id))


@router.post("")
def create_model(data: ModelIn, conn: sqlite3.Connection = Depends(get_conn)):
    _validate(conn, data)
    model_id = db.new_id()
    stamp = db.now()
    conn.execute(
        "INSERT INTO models(id, name, modality, channel_id, upstream_model, description, enabled, "
        "caps, params, price, overrides, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            model_id,
            data.name.strip(),
            data.modality,
            data.channel_id,
            data.upstream_model.strip(),
            data.description,
            int(data.enabled),
            db.dumps(data.caps.model_dump()),
            db.dumps(_normalized_params(data)),
            db.dumps(data.price.model_dump()),
            db.dumps(data.overrides),
            stamp,
            stamp,
        ),
    )
    return serialize(conn, _get(conn, model_id))


@router.put("/{model_id}")
def update_model(model_id: str, data: ModelIn, conn: sqlite3.Connection = Depends(get_conn)):
    _get(conn, model_id)
    _validate(conn, data)
    conn.execute(
        "UPDATE models SET name=?, modality=?, channel_id=?, upstream_model=?, description=?, "
        "enabled=?, caps=?, params=?, price=?, overrides=?, updated_at=? WHERE id=?",
        (
            data.name.strip(),
            data.modality,
            data.channel_id,
            data.upstream_model.strip(),
            data.description,
            int(data.enabled),
            db.dumps(data.caps.model_dump()),
            db.dumps(_normalized_params(data)),
            db.dumps(data.price.model_dump()),
            db.dumps(data.overrides),
            db.now(),
            model_id,
        ),
    )
    return serialize(conn, _get(conn, model_id))


@router.delete("/{model_id}")
def delete_model(model_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    _get(conn, model_id)
    conn.execute("DELETE FROM models WHERE id = ?", (model_id,))
    return {"ok": True}
