"""Generated asset library: listing, files, uploads, favourites, delete."""

from __future__ import annotations

import io
import ipaddress
import socket
import sqlite3
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response

from .. import config, db
from ..core import library, storage
from ..errors import Conflict, NotFound
from .deps import get_conn
from .schemas import AssetPatch, SplitIn, UpscaleIn

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
        "parent_id": row.get("parent_id"),
        "root_id": row.get("root_id"),
        "tool": row.get("tool") or "",
        "version": row.get("version") or 1,
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


def _normalize_refs(raw: list[dict]) -> list[dict]:
    refs: list[dict] = []
    for ref in raw or []:
        if ref.get("source") in ("asset", "library"):
            refs.append(ref)
        elif ref.get("asset_id"):
            refs.append(
                {
                    "source": "asset",
                    "id": ref["asset_id"],
                    "role": ref.get("role") or "reference",
                    "name": ref.get("name") or "",
                    "variant": ref.get("variant") or "base",
                }
            )
        elif ref.get("library_id"):
            refs.append(
                {
                    "source": "library",
                    "id": ref["library_id"],
                    "role": ref.get("role") or "reference",
                    "name": ref.get("name") or "",
                    "variant": ref.get("variant") or "base",
                }
            )
    return refs


def _asset_refs(conn: sqlite3.Connection, row: dict) -> list[dict]:
    meta = db.loads(row.get("meta"), {})
    refs = meta.get("refs_snapshot") or []
    if not refs and row.get("job_id"):
        job = db.one(conn, "SELECT request FROM jobs WHERE id = ?", (row["job_id"],))
        if job:
            refs = db.loads(job.get("request"), {}).get("refs", [])
    items: list[dict] = []
    for ref in _normalize_refs(refs):
        source = ref["source"]
        ref_id = ref.get("id") or ""
        variant = ref.get("variant") or "base"
        item = {
            "role": ref.get("role") or "reference",
            "name": ref.get("name") or "",
            "source": source,
            "id": ref_id,
            "variant": variant,
            "url": "",
            "thumb_url": "",
            "missing": True,
            "_path": None,
        }
        if source == "asset":
            target = db.one(conn, "SELECT * FROM assets WHERE id = ?", (ref_id,))
            if target:
                path = storage.resolve_media(target["path"])
                item.update(
                    {
                        "url": f"/api/assets/{ref_id}/file",
                        "thumb_url": f"/api/assets/{ref_id}/file?size=thumb",
                        "missing": not bool(path),
                        "_path": path,
                    }
                )
        else:
            target = db.one(conn, "SELECT * FROM library_items WHERE id = ?", (ref_id,))
            if target:
                path_value = (
                    target.get("depth_path")
                    if variant == "depth" and target.get("depth_path")
                    else target.get("image_path")
                )
                path = Path(path_value) if path_value else None
                allowed = bool(path and path.is_file() and library.is_allowed(path))
                query = "?variant=depth" if variant == "depth" else ""
                thumb = f"/api/library/{ref_id}/file{query}{'&' if query else '?'}size=thumb"
                item.update(
                    {
                        "url": f"/api/library/{ref_id}/file{query}",
                        "thumb_url": thumb,
                        "missing": not allowed,
                        "_path": path if allowed else None,
                    }
                )
        items.append(item)
    return items


@router.get("/{asset_id}/versions")
def asset_versions(asset_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    row = _asset_or_404(conn, asset_id)
    root = row.get("root_id") or row["id"]
    rows = db.rows(
        conn,
        "SELECT * FROM assets WHERE root_id = ? ORDER BY version, created_at",
        (root,),
    )
    if not rows:
        rows = [row]
    return {
        "root_id": root,
        "current_id": row["id"],
        "items": [serialize(item) for item in rows],
    }


@router.get("/{asset_id}/refs")
def asset_refs(asset_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    row = _asset_or_404(conn, asset_id)
    items = _asset_refs(conn, row)
    for item in items:
        item.pop("_path", None)
    return {"items": items}


@router.get("/{asset_id}/references.zip")
def references_zip(asset_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    row = _asset_or_404(conn, asset_id)
    items = _asset_refs(conn, row)
    if not items:
        raise NotFound("这条作品没有参考图")
    if len(items) > 20:
        raise Conflict("参考图超过 20 张，无法打包")
    buffer = io.BytesIO()
    missing: list[str] = []
    total = 0
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        for index, item in enumerate(items, start=1):
            path: Path | None = item.get("_path")
            if not path or not path.is_file():
                missing.append(f"{index}. {item.get('role')} / {item.get('name') or item.get('id')}")
                continue
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            total += size
            if total > config.MAX_ZIP_BYTES:
                raise Conflict("参考图总大小超过 100MB，无法打包")
            suffix = path.suffix or ".png"
            label = item.get("name") or item.get("role") or "reference"
            safe = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in label)[:48] or "reference"
            bundle.writestr(f"{index:02d}-{item.get('role') or 'reference'}-{safe}{suffix}", path.read_bytes())
        if missing:
            bundle.writestr("missing.txt", "以下参考图已丢失或不在允许目录内：\n" + "\n".join(missing))
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="oneframe-references-{asset_id[:8]}.zip"',
            "Cache-Control": "no-store",
        },
    )


def _validate_public_url(raw: str) -> str:
    value = (raw or "").strip()
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https"):
        raise Conflict("只支持 http 或 https 图片地址")
    if not parts.hostname or parts.username or parts.password:
        raise Conflict("图片地址不合法")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as exc:
        raise Conflict("图片地址端口不合法") from exc
    try:
        infos = socket.getaddrinfo(parts.hostname, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise Conflict("图片地址无法解析") from exc
    for info in infos:
        address = str(info[4][0]).split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            raise Conflict("图片地址解析结果不合法")
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise Conflict("不允许访问内网或本机地址")
    return value


async def _download_remote_image(raw: str) -> tuple[bytes, str, str]:
    current = _validate_public_url(raw)
    async with httpx.AsyncClient(
        follow_redirects=False, timeout=20.0, trust_env=False
    ) as client:
        for _ in range(4):
            async with client.stream("GET", current, headers={"Accept": "image/*"}) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location")
                    if not location:
                        raise Conflict("图片地址重定向缺少目标")
                    current = _validate_public_url(urljoin(current, location))
                    continue
                if response.status_code >= 400:
                    raise Conflict(f"图片下载失败（HTTP {response.status_code}）")
                content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
                length = response.headers.get("content-length")
                if length and length.isdigit() and int(length) > config.MAX_URL_BYTES:
                    raise Conflict("图片超过 25MB 限制")
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > config.MAX_URL_BYTES:
                        raise Conflict("图片超过 25MB 限制")
                    chunks.append(chunk)
                data = b"".join(chunks)
                if not data:
                    raise Conflict("图片内容为空")
                detected = storage.sniff_mime(data)
                if not content_type.startswith("image/") and not detected.startswith("image/"):
                    raise Conflict("该地址不是图片")
                filename = Path(urlsplit(current).path).name or "remote"
                return data, detected if detected.startswith("image/") else content_type, filename
        raise Conflict("图片地址重定向次数过多")


@router.post("/import-url")
async def import_url(
    payload: dict,
    conn: sqlite3.Connection = Depends(get_conn),
):
    url = str(payload.get("url") or "")
    data, mime, filename = await _download_remote_image(url)
    record = storage.save_upload(filename, data, mime)
    asset_id = db.new_id()
    conn.execute(
        """
        INSERT INTO assets
          (id, kind, path, thumb_path, width, height, duration_ms, bytes, prompt, model_name,
           origin, meta, root_id, version, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', '远程素材', 'url', ?, ?, 1, ?)
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
            db.dumps({"source_url": url, "filename": filename}),
            asset_id,
            datetime.now(UTC).isoformat(timespec="seconds"),
        ),
    )
    return serialize(_asset_or_404(conn, asset_id))


def _derived_asset(
    conn: sqlite3.Connection,
    source: dict,
    data: bytes,
    *,
    origin: str,
    tool: str,
    meta: dict,
    parent_id: str | None = None,
    root_id: str | None = None,
    version: int | None = None,
) -> dict:
    record = storage.save_output(data, "image")
    asset_id = db.new_id()
    root = root_id or asset_id
    parent = parent_id or source["id"]
    if version is None:
        version = int(
            db.scalar(
                conn,
                "SELECT COALESCE(MAX(version), 0) + 1 FROM assets WHERE root_id = ?",
                (root,),
            )
            or 1
        )
        if root == asset_id:
            version = 1
    payload = {
        **meta,
        "source_asset_id": source["id"],
    }
    conn.execute(
        """
        INSERT INTO assets
          (id, kind, path, thumb_path, width, height, duration_ms, bytes, job_id, prompt,
           negative, model_id, model_name, params, origin, meta, parent_id, root_id, tool,
           version, created_at)
        VALUES (?, 'image', ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            asset_id,
            record["path"],
            record.get("thumb_path"),
            record.get("width"),
            record.get("height"),
            record.get("bytes"),
            source.get("job_id"),
            source.get("prompt") or "",
            source.get("negative") or "",
            source.get("model_id"),
            source.get("model_name") or "",
            source.get("params") or "{}",
            origin,
            db.dumps(payload),
            parent,
            root,
            tool,
            version,
            db.now(),
        ),
    )
    return serialize(_asset_or_404(conn, asset_id))


@router.post("/{asset_id}/split")
def split_asset(
    asset_id: str,
    data: SplitIn,
    conn: sqlite3.Connection = Depends(get_conn),
):
    source = _asset_or_404(conn, asset_id)
    if source["kind"] != "image":
        raise Conflict("只有图片可以拆分")
    path = storage.resolve_media(source["path"])
    if not path:
        raise NotFound("源文件已丢失")
    total = data.rows * data.columns
    cells = data.cells if data.cells is not None else list(range(total))
    cells = sorted({index for index in cells if 0 <= index < total})
    if not cells:
        raise Conflict("没有选择要拆分的格子")
    if len(cells) > config.MAX_SPLIT_CELLS:
        raise Conflict("一次最多拆分 16 个格子")
    try:
        crops = storage.split_image(path, data.rows, data.columns, cells)
    except ValueError as exc:
        raise Conflict(str(exc)) from exc
    items = []
    for index, raw in crops:
        row, column = divmod(index, data.columns)
        items.append(
            _derived_asset(
                conn,
                source,
                raw,
                origin="split",
                tool="split",
                meta={
                    "grid": {
                        "rows": data.rows,
                        "columns": data.columns,
                        "row": row,
                        "col": column,
                        "index": index,
                    }
                },
            )
        )
    return {"items": items}


@router.post("/{asset_id}/upscale")
def upscale_asset(
    asset_id: str,
    data: UpscaleIn,
    conn: sqlite3.Connection = Depends(get_conn),
):
    source = _asset_or_404(conn, asset_id)
    if source["kind"] != "image":
        raise Conflict("只有图片可以放大")
    path = storage.resolve_media(source["path"])
    if not path:
        raise NotFound("源文件已丢失")
    try:
        raw, width, height = storage.upscale_image(path, data.factor)
    except ValueError as exc:
        raise Conflict(str(exc)) from exc
    root = source.get("root_id") or source["id"]
    version = int(
        db.scalar(conn, "SELECT COALESCE(MAX(version), 0) + 1 FROM assets WHERE root_id = ?", (root,))
        or 1
    )
    return _derived_asset(
        conn,
        source,
        raw,
        origin="upscaled",
        tool="upscale",
        meta={"method": "lanczos", "factor": data.factor, "width": width, "height": height},
        parent_id=source["id"],
        root_id=root,
        version=version,
    )


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
