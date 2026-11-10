"""Reference library endpoints (local indexing, no re-distribution)."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse

from .. import config, db
from ..core import library
from ..core import storage
from ..errors import Conflict, NotFound
from .deps import get_conn
from .schemas import ImportIn, LibraryPatch

router = APIRouter(prefix="/api/library", tags=["library"])

IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".webp": "image/webp", ".gif": "image/gif"}


def _pairs(raw: list[str]) -> list[tuple[str, str]]:
    """Turn repeated ``facet=field:value`` params into (field, value) pairs."""

    pairs: list[tuple[str, str]] = []
    for item in raw:
        field, _, value = item.partition(":")
        field, value = field.strip(), value.strip()
        if field and value:
            pairs.append((field, value))
    return pairs


def _include_nsfw(conn: sqlite3.Connection) -> bool:
    """Content preference lives in Settings → 内容；默认不展示。"""

    return db.setting(conn, "library_nsfw", "0") == "1"


@router.get("")
def list_library(
    kind: str = Query(default="", max_length=20),
    q: str = Query(default="", max_length=200),
    category: str = Query(default="", max_length=120),
    facet: list[str] = Query(default=[]),
    favorite: bool | None = None,
    depth: bool = Query(default=False),
    limit: int = Query(default=48, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    conn: sqlite3.Connection = Depends(get_conn),
):
    return library.list_items(
        conn,
        kind=kind,
        query=q,
        category=category,
        facets=_pairs(facet),
        favorite=favorite,
        depth_only=depth,
        limit=limit,
        offset=offset,
        include_nsfw=_include_nsfw(conn),
    )


@router.get("/facets")
def facets(
    kind: str = Query(default="", max_length=20),
    q: str = Query(default="", max_length=200),
    facet: list[str] = Query(default=[]),
    favorite: bool | None = None,
    conn: sqlite3.Connection = Depends(get_conn),
):
    data = library.facets(
        conn,
        kind=kind,
        query=q,
        favorite=favorite,
        selected=_pairs(facet),
        include_nsfw=_include_nsfw(conn),
    )
    data["roots"] = [str(path) for path in library.allowed_roots()]
    data["grand_total"] = db.scalar(conn, "SELECT COUNT(*) FROM library_items") or 0
    return data


@router.post("/reclassify")
def reclassify():
    with db.connect() as conn:
        return library.rebuild_taxonomy(conn)


@router.get("/random")
def random_library(
    kind: str = Query(default="", max_length=20),
    q: str = Query(default="", max_length=200),
    category: str = Query(default="", max_length=120),
    facet: list[str] = Query(default=[]),
    exclude: str = Query(default="", max_length=500),
    conn: sqlite3.Connection = Depends(get_conn),
):
    item = library.random_item(
        conn,
        kind=kind,
        query=q,
        category=category,
        facets=_pairs(facet),
        exclude=[value for value in exclude.split(",") if value],
        include_nsfw=_include_nsfw(conn),
    )
    if not item:
        raise NotFound("没有匹配的素材")
    return item


@router.get("/{item_id}/variants")
def item_variants(item_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    data = library.item_variants(conn, item_id)
    if not data:
        raise NotFound("素材不存在")
    return data


@router.post("/assets/{asset_id}")
def import_asset(asset_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    """Save one generated work into the reference library (index in place)."""

    asset = db.one(conn, "SELECT * FROM assets WHERE id = ?", (asset_id,))
    if not asset:
        raise NotFound("作品不存在")
    if asset["kind"] != "image":
        raise Conflict("只有图片作品可以加入参考库")
    item_id, created = library.add_asset_reference(conn, asset)
    row = db.one(conn, "SELECT * FROM library_items WHERE id = ?", (item_id,))
    row["facets"] = library.item_facets(conn, item_id)
    return {"item": library.serialize_item(row), "created": created}


@router.post("/import")
async def import_library(data: ImportIn, conn: sqlite3.Connection = Depends(get_conn)):
    try:
        if data.mode == "pose_gallery":
            result = await asyncio.to_thread(library.import_pose_gallery, data.path)
        else:
            result = await asyncio.to_thread(library.import_folder, data.path, data.kind)
    except PermissionError as exc:
        raise Conflict(str(exc)) from exc
    except FileNotFoundError as exc:
        raise NotFound(str(exc)) from exc
    return result


@router.patch("/{item_id}")
def patch_item(item_id: str, data: LibraryPatch, conn: sqlite3.Connection = Depends(get_conn)):
    row = db.one(conn, "SELECT * FROM library_items WHERE id = ?", (item_id,))
    if not row:
        raise NotFound("素材不存在")
    if data.favorite is not None:
        conn.execute("UPDATE library_items SET favorite=? WHERE id=?", (int(data.favorite), item_id))
    if data.tags is not None:
        conn.execute("UPDATE library_items SET tags=? WHERE id=?", (data.tags, item_id))
    row = db.one(conn, "SELECT * FROM library_items WHERE id = ?", (item_id,))
    row["facets"] = library.item_facets(conn, item_id)
    return library.serialize_item(row)


@router.delete("/{item_id}")
def delete_item(item_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    library.delete_item(conn, item_id)
    return {"ok": True}


@router.get("/{item_id}/file")
def item_file(
    item_id: str,
    size: str = Query(default="full"),
    variant: str = Query(default="base"),
    conn: sqlite3.Connection = Depends(get_conn),
):
    if variant not in ("base", "depth"):
        raise Conflict("不支持的图片版本")
    try:
        path, _ = library.file_for(
            conn, item_id, prefer_thumb=size == "thumb", variant=variant
        )
    except FileNotFoundError as exc:
        raise NotFound(str(exc)) from exc
    media_type = IMAGE_TYPES.get(path.suffix.lower(), "image/webp")
    return FileResponse(
        path, media_type=media_type, headers={"Cache-Control": "public, max-age=86400"}
    )


@router.post("/upload")
def upload_reference(
    files: list[UploadFile] = File(...),
    kind: str = Query(default="custom"),
    conn: sqlite3.Connection = Depends(get_conn),
):
    created = []
    for upload_file in files[:8]:
        data = upload_file.file.read(config.MAX_UPLOAD_BYTES + 1)
        if not data:
            continue
        record = storage.save_upload(upload_file.filename or "reference", data, upload_file.content_type)
        item_id = library.add_uploaded(
            conn,
            kind=kind,
            filename=upload_file.filename or "上传素材",
            image_path=record["path"],
            thumb_path=record.get("thumb_path"),
            width=record.get("width"),
            height=record.get("height"),
        )
        row = db.one(conn, "SELECT * FROM library_items WHERE id = ?", (item_id,))
        row["facets"] = library.item_facets(conn, item_id)
        created.append(library.serialize_item(row))
    return {"items": created}
