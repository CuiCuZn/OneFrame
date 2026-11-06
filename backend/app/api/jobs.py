"""Job listing, detail, cancel and retry."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from fastapi import APIRouter, Depends, Query

from .. import db
from ..core import worker
from ..errors import Conflict, NotFound
from .deps import get_conn

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

TERMINAL = ("succeeded", "failed", "canceled", "uncertain")


def duration_ms(row: dict) -> int | None:
    start = row.get("started_at") or row.get("created_at")
    end = row.get("finished_at")
    if not start or not end:
        return None
    try:
        seconds = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
    except ValueError:
        return None
    return max(0, int(seconds * 1000))


def serialize_job(conn: sqlite3.Connection, row: dict, detail: bool = False) -> dict:
    assets = db.rows(
        conn,
        "SELECT id, kind, path, thumb_path, width, height, duration_ms, bytes, favorite, tags, "
        "prompt, negative, model_name, params, created_at "
        "FROM assets WHERE job_id = ? ORDER BY created_at",
        (row["id"],),
    )
    for asset in assets:
        asset["url"] = f"/api/assets/{asset['id']}/file"
        asset["thumb_url"] = f"/api/assets/{asset['id']}/file?size=thumb"
        asset["download_url"] = f"/api/assets/{asset['id']}/file?dl=1"
        asset["params"] = db.loads(asset.get("params"), {})
        asset.pop("path", None)
        asset.pop("thumb_path", None)
    channel_name = row.get("channel_name") or ""
    if not channel_name:
        req = db.loads(row.get("request"), {})
        channel_name = req.get("channel_name", "")
    if not channel_name and row.get("channel_id"):
        ch = db.one(conn, "SELECT name FROM channels WHERE id = ?", (row["channel_id"],))
        if ch:
            channel_name = ch["name"]

    data = {
        "id": row["id"],
        "model_id": row["model_id"],
        "model_name": row["model_name"],
        "channel_id": row.get("channel_id"),
        "channel_name": channel_name,
        "modality": row["modality"],
        "status": row["status"],
        "stage": row["stage"],
        "progress": row["progress"],
        "error": row["error"],
        "price": row["price"],
        "currency": row["currency"],
        "external_url": row["external_url"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "duration_ms": duration_ms(row),
        "prompt": db.loads(row["request"], {}).get("prompt", ""),
        "canceled": bool(row["canceled"]),
        "assets": assets,
        "asset_count": len(assets),
    }
    if detail:
        data["request"] = db.loads(row["request"], {})
        data["attempts"] = db.loads(row["attempts"], [])
    return data


@router.get("")
def list_jobs(
    status: str = Query(default="", max_length=40),
    modality: str = Query(default="", max_length=10),
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=30, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    conn: sqlite3.Connection = Depends(get_conn),
):
    clauses: list[str] = []
    args: list = []
    if status == "active":
        clauses.append("status IN ('queued','submitting','running')")
    elif status:
        clauses.append("status = ?")
        args.append(status)
    if modality:
        clauses.append("modality = ?")
        args.append(modality)
    if q:
        clauses.append("(model_name LIKE ? OR channel_name LIKE ? OR request LIKE ?)")
        like = f"%{q}%"
        args.extend([like, like, like])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    total = db.scalar(conn, f"SELECT COUNT(*) FROM jobs {where}", args) or 0
    rows = db.rows(
        conn,
        f"SELECT * FROM jobs {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        [*args, limit, offset],
    )
    return {"items": [serialize_job(conn, row) for row in rows], "total": total}


@router.get("/{job_id}")
def get_job(job_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    row = db.one(conn, "SELECT * FROM jobs WHERE id = ?", (job_id,))
    if not row:
        raise NotFound("任务不存在")
    return serialize_job(conn, row, detail=True)


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    row = db.one(conn, "SELECT * FROM jobs WHERE id = ?", (job_id,))
    if not row:
        raise NotFound("任务不存在")
    if row["status"] in terminal_states():
        return {"ok": False, "message": "任务已结束"}
    if row["status"] == "queued":
        conn.execute(
            "UPDATE jobs SET status='canceled', canceled=1, stage='已取消', finished_at=? WHERE id=?",
            (db.now(), job_id),
        )
        return {"ok": True, "message": "已取消"}
    conn.execute("UPDATE jobs SET canceled=1, stage='取消中' WHERE id=?", (job_id,))
    return {"ok": True, "message": "已请求取消，将在下次轮询时停止"}


@router.post("/{job_id}/retry")
async def retry_job(job_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    row = db.one(conn, "SELECT * FROM jobs WHERE id = ?", (job_id,))
    if not row:
        raise NotFound("任务不存在")
    if row["status"] not in ("failed", "canceled", "uncertain"):
        raise Conflict("只有失败、取消或待核对的任务可以重试")
    await worker.runner.retry(job_id)
    return {"ok": True}


@router.delete("/{job_id}")
def delete_job(job_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    row = db.one(conn, "SELECT * FROM jobs WHERE id = ?", (job_id,))
    if not row:
        raise NotFound("任务不存在")
    if row["status"] not in terminal_states():
        raise Conflict("任务进行中，请先取消")
    count = db.scalar(conn, "SELECT COUNT(*) FROM assets WHERE job_id = ?", (job_id,)) or 0
    conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    return {"ok": True, "kept_assets": int(count)}


def terminal_states() -> tuple[str, ...]:
    return ("succeeded", "failed", "canceled", "uncertain")
