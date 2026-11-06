"""Generated asset library: listing, files, uploads, favourites, delete."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from .. import config, db
from ..core import storage
from ..errors import Conflict, NotFound
from .deps import get_conn
from .schemas import AssetPatch

router = APIRouter(prefix="/api/assets", tags=["assets"])

MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
}


def serialize(row: dict) -> dict:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "width": row["width"],
        "height": row["height"],
        "duration_ms": row["duration_ms"],
        "bytes": row["bytes"],
        "prompt": row["prompt"],
        "negative": row["negative"],
        "model_id": row["model_id"],
        "model_name": row["model_name"],
        "params": db.loads(row["params"], {}),
        "favorite": bool(row["favorite"]),
        "tags": row["tags"],
        "origin": row["origin"],
        "job_id": row["job_id"],
        "created_at": row["created_at"],
        "meta": db.loads(row["meta"], {}),
        "url": f"/api/assets/{row['id']}/file",
        "thumb_url": f"/api/assets/{row['id']}/file?size=thumb",
        "download_url": f"/api/assets/{row['id']}/file?dl=1",
    }


def _asset_or_404(conn: sqlite3.Connection, asset_id: str) -> dict:
    row = db.one(conn, "SELECT * FROM assets WHERE id = ?", (asset_id,))
    if not row:
        raise NotFound("作品不存在")
    return row


@router.get("")
def list_assets(
    kind: str = Query(default="", max_length=10),
    favorite: bool | None = None,
    q: str = Query(default="", max_length=200),
    model: str = Query(default="", max_length=80),
    limit: int = Query(default=40, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    conn: sqlite3.Connection = Depends(get_conn),
):
    clauses: list[str] = []
    args: list = []
    if kind:
        clauses.append("kind = ?")
        args.append(kind)
    if favorite is not None:
        clauses.append("favorite = ?")
        args.append(int(favorite))
    if q:
        clauses.append("(prompt LIKE ? OR tags LIKE ? OR model_name LIKE ?)")
        like = f"%{q}%"
        args.extend([like, like, like])
    if model:
        clauses.append("model_id = ?")
        args.append(model)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    total = db.scalar(conn, f"SELECT COUNT(*) FROM assets {where}", args) or 0
    rows = db.rows(
        conn,
        f"SELECT * FROM assets {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        [*args, limit, offset],
    )
    return {"items": [serialize(row) for row in rows], "total": total}


@router.get("/stats")
def asset_stats(conn: sqlite3.Connection = Depends(get_conn)):
    by_kind = db.rows(conn, "SELECT kind, COUNT(*) AS count FROM assets GROUP BY kind")
    favorite = db.scalar(conn, "SELECT COUNT(*) FROM assets WHERE favorite = 1") or 0
    return {
        "total": db.scalar(conn, "SELECT COUNT(*) FROM assets") or 0,
        "favorite": favorite,
        "by_kind": {row["kind"]: row["count"] for row in by_kind},
    }


@router.get("/{asset_id}")
def get_asset(asset_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    return serialize(_asset_or_404(conn, asset_id))


@router.patch("/{asset_id}")
def patch_asset(
    asset_id: str, data: AssetPatch, conn: sqlite3.Connection = Depends(get_conn)
):
    _asset_or_404(conn, asset_id)
    if data.favorite is not None:
        conn.execute("UPDATE assets SET favorite = ? WHERE id = ?", (int(data.favorite), asset_id))
    if data.tags is not None:
        conn.execute("UPDATE assets SET tags = ? WHERE id = ?", (data.tags, asset_id))
    return serialize(_asset_or_404(conn, asset_id))


@router.delete("/{asset_id}")
def delete_asset(asset_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    row = _asset_or_404(conn, asset_id)
    storage.delete_files(row["path"], row["thumb_path"], row["poster_path"])
    conn.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
    conn.execute(
        "DELETE FROM library_items WHERE source = 'asset' AND external_id = ?", (asset_id,)
    )
    return {"ok": True}


@router.get("/{asset_id}/file")
def asset_file(
    asset_id: str,
    size: str = Query(default="full"),
    dl: int = Query(default=0),
    conn: sqlite3.Connection = Depends(get_conn),
):
    row = _asset_or_404(conn, asset_id)
    rel = row["thumb_path"] if size == "thumb" and row["thumb_path"] else row["path"]
    path = storage.resolve_media(rel) if rel else None
    if not path:
        path = storage.resolve_media(row["path"])
    if not path:
        raise HTTPException(status_code=404, detail="文件已丢失")
    media_type = MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
    filename = f"oneframe-{asset_id[:8]}{path.suffix}"
    if dl:
        return FileResponse(path, media_type=media_type, filename=filename)
    return FileResponse(
        path,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.get("/{asset_id}/draft")
def reuse_draft(asset_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    row = _asset_or_404(conn, asset_id)
    return {
        "prompt": row["prompt"],
        "negative": row["negative"],
        "model_id": row["model_id"],
        "params": db.loads(row["params"], {}),
        "refs": [{"asset_id": asset_id, "role": "reference", "name": "上一版结果"}],
    }


@router.post("/upload")
def upload(
    files: list[UploadFile] = File(...),
    conn: sqlite3.Connection = Depends(get_conn),
):
    created = []
    for upload_file in files[:8]:
        data = upload_file.file.read(config.MAX_UPLOAD_BYTES + 1)
        if len(data) > config.MAX_UPLOAD_BYTES:
            raise Conflict(f"{upload_file.filename} 超过 {config.MAX_UPLOAD_BYTES // 1024 // 1024}MB 限制")
        if not data:
            continue
        record = storage.save_upload(upload_file.filename or "upload", data, upload_file.content_type)
        asset_id = db.new_id()
        conn.execute(
            """
            INSERT INTO assets
              (id, kind, path, thumb_path, width, height, duration_ms, bytes, prompt, model_name,
               origin, meta, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', '上传素材', 'upload', ?, ?)
            """,
            (
                asset_id,
                record.get("kind", "image"),
                record["path"],
                record.get("thumb_path"),
                record.get("width"),
                record.get("height"),
                record.get("duration_ms"),
                record.get("bytes"),
                db.dumps({"filename": upload_file.filename}),
                datetime.now(UTC).isoformat(timespec="seconds"),
            ),
        )
        created.append(serialize(_asset_or_404(conn, asset_id)))
    return {"items": created}
