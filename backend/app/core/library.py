"""Reference library: index a local folder or an existing pose-gallery checkout.

Images are *never* copied into the app's media store by default.  We only index
paths the user already has on disk, so third-party reference material stays on
the user's machine and is not redistributed by OneFrame.

Classification lives in :mod:`app.core.taxonomy`; this module stores the
resulting category path / facet rows and answers faceted queries.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageOps

from .. import config, db
from . import storage, taxonomy

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif", ".bmp"}
VIDEO_SUFFIXES = {".mp4", ".webm", ".mov", ".mkv"}

GALLERY_FILES: tuple[tuple[str, str], ...] = (
    ("pose", "pose-zh.json"),
    ("costume", "costume-zh.json"),
    ("portrait", "portrait-zh.json"),
    ("costume", "costume-shisei-zh.json"),
)
GALLERY_REMOTE_FILES: tuple[str, ...] = (
    "costume-gia-anime-zh.json",
    "costume-anime-zh.json",
)
GALLERY_TITLE_KEYS = {"pose": "姿势名称", "costume": "服装名称", "portrait": "标题"}


def allowed_roots() -> list[Path]:
    """Data dir + env roots + roots saved from the Settings page."""

    roots = [config.DATA_DIR, *config.LIBRARY_ROOTS]
    try:
        with db.connect() as conn:
            row = db.one(conn, "SELECT v FROM settings WHERE k = 'library_roots'")
        if row and row["v"]:
            for raw in str(row["v"]).split(";"):
                raw = raw.strip()
                if raw:
                    roots.append(Path(raw).expanduser())
    except Exception:  # pragma: no cover - settings may not exist yet
        pass
    return roots


def is_allowed(path: Path) -> bool:
    resolved = path.resolve()
    return any(
        resolved == root or root in resolved.parents for root in (r.resolve() for r in allowed_roots())
    )


def resolve_allowed(path: str) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = (config.BASE_DIR / candidate)
    if not is_allowed(candidate):
        raise PermissionError("该路径不在允许的素材目录内（可用 ONEFRAME_LIBRARY_ROOTS 扩展）")
    return candidate.resolve()


def _thumb(source: Path) -> str | None:
    """Thumbnail for external files lives under data/thumbs/library."""

    digest = hashlib.sha1(str(source).encode("utf-8")).hexdigest()
    target = config.THUMB_DIR / "library" / f"{digest}.webp"
    if target.exists():
        return target.relative_to(config.DATA_DIR).as_posix()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with Image.open(source) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((520, 520), Image.LANCZOS)
            image.save(target, "WEBP", quality=82, method=4)
        return target.relative_to(config.DATA_DIR).as_posix()
    except Exception:
        return None


def _insert(conn: sqlite3.Connection, item: dict[str, Any]) -> str | None:
    """Insert one row plus its facet rows.  Returns the new id, or None if seen."""

    exists = db.one(
        conn,
        "SELECT id FROM library_items WHERE source = ? AND external_id = ?",
        (item["source"], item["external_id"]),
    )
    if exists:
        _update_variant_fields(conn, exists["id"], item)
        return None

    item_id = item.get("id") or db.new_id()
    conn.execute(
        """
        INSERT INTO library_items
          (id, source, external_id, kind, title, subtitle, category, category_path,
           tags, search_text, image_path, thumb_path, depth_path, depth_thumb_path,
           has_depth, group_key, variant_label, width, height, favorite, nsfw,
           meta, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
        """,
        (
            item_id,
            item["source"],
            item["external_id"],
            item.get("kind", "other"),
            item.get("title", "")[:300],
            item.get("subtitle", "")[:300],
            item.get("category", "")[:120],
            item.get("category_path", "")[:300],
            item.get("tags", "")[:500],
            item.get("search_text", "")[:2000],
            item["image_path"],
            item.get("thumb_path"),
            item.get("depth_path"),
            item.get("depth_thumb_path"),
            int(bool(item.get("has_depth"))),
            item.get("group_key", ""),
            item.get("variant_label", "")[:80],
            item.get("width"),
            item.get("height"),
            int(bool(item.get("nsfw"))),
            db.dumps(item.get("meta", {})),
            db.now(),
        ),
    )
    facets = item.get("facets") or []
    if facets:
        conn.executemany(
            "INSERT OR IGNORE INTO library_facets (item_id, field, value, level) VALUES (?, ?, ?, ?)",
            [(item_id, field, value, int(level)) for field, value, level in facets],
        )
    return item_id


def _update_variant_fields(conn: sqlite3.Connection, item_id: str, item: dict[str, Any]) -> None:
    fields: list[str] = []
    args: list[Any] = []
    for key in ("group_key", "variant_label", "depth_path", "depth_thumb_path"):
        value = item.get(key)
        if value:
            fields.append(f"{key} = ?")
            args.append(value)
    if item.get("has_depth"):
        fields.append("has_depth = 1")
    if not fields:
        return
    conn.execute(
        f"UPDATE library_items SET {', '.join(fields)} WHERE id = ?", (*args, item_id)
    )


def _classification_fields(classification: taxonomy.Classification) -> dict[str, Any]:
    return {
        "category": classification.category,
        "category_path": classification.category_path,
        "tags": classification.tags,
        "search_text": classification.search_text,
        "nsfw": classification.nsfw,
        "facets": classification.facets,
    }


def import_folder(path: str, kind: str = "other", limit: int = 5000) -> dict[str, Any]:
    root = resolve_allowed(path)
    if not root.exists():
        raise FileNotFoundError(f"目录不存在：{root}")
    if root.is_file():
        files = [root]
    else:
        files = [
            item
            for item in root.rglob("*")
            if item.is_file() and item.suffix.lower() in IMAGE_SUFFIXES | VIDEO_SUFFIXES
        ][:limit]
    added = 0
    with db.connect() as conn:
        for file in files:
            if file.suffix.lower() in VIDEO_SUFFIXES:
                continue
            try:
                with Image.open(file) as image:
                    width, height = image.size
            except Exception:
                width = height = None
            relative = file.relative_to(root).as_posix() if root.is_dir() else file.name
            classification = taxonomy.classify_folder(relative, file.stem)
            item = {
                "source": f"folder:{root}",
                "external_id": relative,
                "kind": kind,
                "title": file.stem,
                "subtitle": relative,
                **_classification_fields(classification),
                "image_path": str(file),
                "thumb_path": _thumb(file),
                "width": width,
                "height": height,
                "meta": {"size": file.stat().st_size},
            }
            added += int(bool(_insert(conn, item)))
    return {"added": added, "scanned": len(files), "root": str(root)}


def _load_json(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(payload, dict):
        for key in ("items", "data", "list"):
            if isinstance(payload.get(key), list):
                return payload[key]
        return []
    return payload if isinstance(payload, list) else []


def _shisei_views(entry: dict) -> list[dict]:
    raw = entry.get("views")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = []
    return [view for view in raw if isinstance(view, dict)] if isinstance(raw, list) else []


def _depth_files(base: Path, pose_id: str) -> tuple[Path | None, Path | None]:
    if not pose_id:
        return None, None
    depth = thumb = None
    for suffix in (".webp", ".png", ".jpg", ".jpeg"):
        candidate = base / "img" / "depth" / f"{pose_id}{suffix}"
        if candidate.is_file():
            depth = candidate
            break
    for suffix in (".webp", ".png", ".jpg", ".jpeg"):
        candidate = base / "thumbs" / "depth" / f"{pose_id}{suffix}"
        if candidate.is_file():
            thumb = candidate
            break
    return depth, thumb


def import_pose_gallery(root: str) -> dict[str, Any]:
    """Adopt an existing ai-pose-gallery-zh checkout in place.

    Expects the gallery JSON under ``data/`` plus ``img/`` and ``thumbs/``.
    Local images are indexed in place; remote hotlinks are counted and skipped.
    """

    base = resolve_allowed(root)
    data_dir = base / "data"
    if not data_dir.exists():
        raise FileNotFoundError("没有找到 data/ 目录，请选择 ai-pose-gallery-zh 仓库根目录")

    added = updated = scanned = skipped_missing = depth_added = 0
    skipped_remote = 0
    sources: dict[str, int] = {}
    source_id = f"pose-gallery:{base}"

    with db.connect() as conn:
        for kind, filename in GALLERY_FILES:
            entries = _load_json(data_dir / filename)
            scanned += len(entries)
            sources[kind] = sources.get(kind, 0) + len(entries)
            title_key = GALLERY_TITLE_KEYS[kind]
            for entry in entries:
                if filename == "costume-shisei-zh.json":
                    views = _shisei_views(entry)
                    if not views:
                        views = [{"id": "selected", "label": "", "原图": entry.get("原图"), "预览图": entry.get("预览图"), "缩略图": entry.get("缩略图")}]
                    for view in views:
                        image_rel = view.get("原图") or view.get("预览图") or entry.get("原图")
                        if not image_rel or str(image_rel).startswith(("http://", "https://")):
                            skipped_remote += 1
                            continue
                        image_path = (base / image_rel).resolve()
                        if not image_path.exists() or not is_allowed(image_path):
                            skipped_missing += 1
                            continue
                        thumb_rel = view.get("缩略图") or entry.get("缩略图")
                        thumb_path = (base / thumb_rel).resolve() if thumb_rel else None
                        if not thumb_path or not thumb_path.exists():
                            computed = _thumb(image_path)
                            thumb_value = str(config.DATA_DIR / computed) if computed else None
                        else:
                            thumb_value = str(thumb_path)
                        view_label = str(view.get("label") or "")
                        set_title = str(entry.get(title_key) or entry.get("id") or "")
                        payload = {
                            **entry,
                            "服装名称": f"{set_title} · {view_label}" if view_label else set_title,
                            "视角": view_label,
                            "id": f"{entry.get('id')}:{view.get('id')}",
                        }
                        classification = taxonomy.classify_costume(payload)
                        external_id = f"costume-view:{entry.get('id')}:{view.get('id')}"
                        item = {
                            "source": source_id,
                            "external_id": external_id,
                            "kind": "costume",
                            "title": payload["服装名称"],
                            "subtitle": str(entry.get("id") or ""),
                            **_classification_fields(classification),
                            "image_path": str(image_path),
                            "thumb_path": thumb_value,
                            "group_key": f"shisei:{entry.get('id')}",
                            "variant_label": view_label,
                            "width": None,
                            "height": None,
                            "meta": {
                                "set_id": entry.get("id"),
                                "set_title": set_title,
                                "view": view_label,
                                "view_id": view.get("id"),
                                "source_repo": "anhao/ai-pose-gallery-zh",
                            },
                        }
                        exists = db.one(
                            conn,
                            "SELECT id FROM library_items WHERE source = ? AND external_id = ?",
                            (source_id, external_id),
                        )
                        if exists:
                            _update_variant_fields(conn, exists["id"], item)
                            updated += 1
                        else:
                            added += int(bool(_insert(conn, item)))
                    continue

                image_rel = entry.get("原图") or entry.get("预览图")
                if not image_rel:
                    continue
                if str(image_rel).startswith(("http://", "https://")):
                    skipped_remote += 1
                    continue
                image_path = (base / image_rel).resolve()
                if not image_path.exists() or not is_allowed(image_path):
                    skipped_missing += 1
                    continue
                thumb_rel = entry.get("缩略图")
                thumb_path = (base / thumb_rel).resolve() if thumb_rel else None
                if thumb_path and thumb_path.exists():
                    thumb_value = str(thumb_path)
                else:
                    computed = _thumb(image_path)
                    thumb_value = str(config.DATA_DIR / computed) if computed else None

                classification = taxonomy.classify_entry(kind, entry)
                title = str(entry.get(title_key) or entry.get("标题") or entry.get("名称") or entry.get("id") or "")
                code = str(entry.get("姿势编号") or "")
                pose_id = str(entry.get("id") or "")
                angle = str(entry.get("角度") or "")
                depth_path = depth_thumb = None
                if kind == "pose":
                    depth_path, depth_thumb = _depth_files(base, pose_id)
                    if depth_path:
                        depth_added += 1
                meta: dict[str, Any] = {
                    "angle": entry.get("角度"),
                    "series": entry.get("体系"),
                    "code": entry.get("姿势编号"),
                    "keywords": entry.get("关键词"),
                    "source_repo": "anhao/ai-pose-gallery-zh",
                }
                if kind == "portrait":
                    meta.update({"featured": entry.get("精选"), "popular": entry.get("热门")})
                if kind == "pose":
                    group_key = f"pose:{entry.get('体系')}:{code}" if code else f"pose:{pose_id}"
                elif kind == "costume":
                    group_key = f"costume:{pose_id}"
                elif kind == "portrait":
                    group_key = f"portrait:{pose_id}"
                else:
                    group_key = pose_id
                item = {
                    "source": source_id,
                    "external_id": f"{kind}:{pose_id}",
                    "kind": kind,
                    "title": title,
                    "subtitle": str(entry.get("id") or ""),
                    **_classification_fields(classification),
                    "image_path": str(image_path),
                    "thumb_path": thumb_value,
                    "depth_path": str(depth_path) if depth_path else None,
                    "depth_thumb_path": str(depth_thumb) if depth_thumb else None,
                    "has_depth": bool(depth_path),
                    "group_key": group_key,
                    "variant_label": angle,
                    "width": entry.get("宽") or None,
                    "height": entry.get("高") or None,
                    "meta": meta,
                }
                exists = db.one(
                    conn,
                    "SELECT id FROM library_items WHERE source = ? AND external_id = ?",
                    (source_id, item["external_id"]),
                )
                if exists:
                    _update_variant_fields(conn, exists["id"], item)
                    updated += 1
                else:
                    added += int(bool(_insert(conn, item)))

        for filename in GALLERY_REMOTE_FILES:
            for entry in _load_json(data_dir / filename):
                scanned += 1
                image_rel = entry.get("原图") or entry.get("预览图") or ""
                if str(image_rel).startswith(("http://", "https://")):
                    skipped_remote += 1

    return {
        "added": added,
        "updated": updated,
        "scanned": scanned,
        "skipped_remote": skipped_remote,
        "skipped_missing": skipped_missing,
        "depth_added": depth_added,
        "sources": sources,
        "root": str(base),
    }


def add_uploaded(
    conn: sqlite3.Connection,
    *,
    kind: str,
    filename: str,
    image_path: str,
    thumb_path: str | None,
    width: int | None,
    height: int | None,
    meta: dict[str, Any] | None = None,
) -> str:
    """Register one uploaded reference image (already stored on disk)."""

    title = Path(filename or "上传素材").stem
    classification = taxonomy.classify_upload(title)
    item_id = db.new_id()
    item = {
        "id": item_id,
        "source": "upload",
        "external_id": item_id,
        "kind": kind,
        "title": title,
        "subtitle": filename,
        **_classification_fields(classification),
        "image_path": image_path,
        "thumb_path": thumb_path,
        "width": width,
        "height": height,
        "meta": meta or {"filename": filename},
    }
    _insert(conn, item)
    return item_id


def add_asset_reference(conn: sqlite3.Connection, asset: dict) -> tuple[str, bool]:
    """Save a generated work into the reference library (no file copies).

    Returns ``(library_item_id, created)``; calling it twice is a no-op.
    """

    existing = db.one(
        conn,
        "SELECT id FROM library_items WHERE source = 'asset' AND external_id = ?",
        (asset["id"],),
    )
    if existing:
        return existing["id"], False

    prompt = (asset.get("prompt") or "").strip().splitlines()
    title = (prompt[0] if prompt else "")[:80] or f"作品 {str(asset['id'])[:8]}"
    classification = taxonomy.classify_work(title)
    item_id = db.new_id()
    thumb = asset.get("thumb_path") or asset.get("path")
    item = {
        "id": item_id,
        "source": "asset",
        "external_id": asset["id"],
        "kind": "work",
        "title": title,
        "subtitle": asset.get("model_name") or "",
        **_classification_fields(classification),
        "image_path": str(config.DATA_DIR / asset["path"]),
        "thumb_path": str(config.DATA_DIR / thumb) if thumb else None,
        "width": asset.get("width"),
        "height": asset.get("height"),
        "meta": {
            "asset_id": asset["id"],
            "model_name": asset.get("model_name"),
            "created_at": asset.get("created_at"),
        },
    }
    _insert(conn, item)
    return item_id, True


# ── queries ───────────────────────────────────────────────────────────────


def _scope(
    *,
    kind: str = "",
    query: str = "",
    favorite: bool | None = None,
    selected: Iterable[tuple[str, str]] = (),
    exclude: Iterable[str] = (),
    depth_only: bool = False,
    include_nsfw: bool = True,
) -> tuple[str, list[Any]]:
    """WHERE clause over ``library_items i`` for the current browse state."""

    clauses: list[str] = []
    args: list[Any] = []
    if kind:
        clauses.append("i.kind = ?")
        args.append(kind)
    if not include_nsfw:
        clauses.append("i.nsfw = 0")
    if depth_only:
        clauses.append("i.has_depth = 1")
    for token in taxonomy.query_tokens(query):
        clauses.append("i.search_text LIKE ?")
        args.append(f"%{token}%")
    if favorite:
        clauses.append("i.favorite = 1")

    grouped: dict[str, list[str]] = {}
    for field, value in selected:
        grouped.setdefault(field, []).append(value)
    skipped = set(exclude)
    for field, values in grouped.items():
        if field in skipped:
            continue
        marks = ",".join("?" for _ in values)
        clauses.append(
            "EXISTS (SELECT 1 FROM library_facets f WHERE f.item_id = i.id "
            f"AND f.field = ? AND f.value IN ({marks}))"
        )
        args.extend([field, *values])
    return (" AND ".join(clauses) if clauses else "1=1"), args


def _attach_facets(conn: sqlite3.Connection, rows: list[dict]) -> None:
    ids = [row["id"] for row in rows]
    if not ids:
        return
    marks = ",".join("?" for _ in ids)
    facet_rows = db.rows(
        conn,
        f"SELECT item_id, field, value FROM library_facets "
        f"WHERE item_id IN ({marks}) ORDER BY level, field, value",
        ids,
    )
    grouped: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for facet in facet_rows:
        grouped[facet["item_id"]][facet["field"]].append(facet["value"])
    for row in rows:
        row["facets"] = {field: values for field, values in grouped.get(row["id"], {}).items()}


def item_facets(conn: sqlite3.Connection, item_id: str) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for row in db.rows(
        conn,
        "SELECT field, value FROM library_facets WHERE item_id = ? ORDER BY level, field, value",
        (item_id,),
    ):
        grouped.setdefault(row["field"], []).append(row["value"])
    return grouped


def serialize_item(row: dict) -> dict[str, Any]:
    item = dict(row)
    item["meta"] = db.loads(item.get("meta"), {})
    item["url"] = f"/api/library/{item['id']}/file"
    item["thumb_url"] = f"/api/library/{item['id']}/file?size=thumb"
    if item.get("has_depth") and item.get("depth_path"):
        item["depth_url"] = f"/api/library/{item['id']}/file?variant=depth"
        item["depth_thumb_url"] = f"/api/library/{item['id']}/file?variant=depth&size=thumb"
    else:
        item["depth_url"] = None
        item["depth_thumb_url"] = None
    item.pop("image_path", None)
    item.pop("thumb_path", None)
    item.pop("depth_path", None)
    item.pop("depth_thumb_path", None)
    item.pop("search_text", None)
    return item


def item_variants(conn: sqlite3.Connection, item_id: str) -> dict[str, Any] | None:
    item = db.one(conn, "SELECT * FROM library_items WHERE id = ?", (item_id,))
    if not item:
        return None
    group_key = item.get("group_key") or item.get("external_id") or item["id"]
    rows = db.rows(
        conn,
        "SELECT * FROM library_items WHERE group_key = ? ORDER BY variant_label, created_at, title",
        (group_key,),
    )
    _attach_facets(conn, rows)
    return {"group_key": group_key, "items": [serialize_item(row) for row in rows]}


def random_item(
    conn: sqlite3.Connection,
    *,
    kind: str = "",
    query: str = "",
    category: str = "",
    facets: Iterable[tuple[str, str]] = (),
    exclude: Iterable[str] = (),
    include_nsfw: bool = True,
) -> dict[str, Any] | None:
    where, args = _scope(
        kind=kind,
        query=query,
        selected=facets,
        exclude=exclude,
        include_nsfw=include_nsfw,
    )
    if category:
        where += (
            " AND EXISTS (SELECT 1 FROM library_facets f WHERE f.item_id = i.id"
            " AND f.level <= 2 AND f.value = ?)"
        )
        args.append(category)
    excluded = [item for item in exclude if item]
    if excluded:
        marks = ",".join("?" for _ in excluded)
        where += f" AND i.id NOT IN ({marks})"
        args.extend(excluded)
    row = db.one(
        conn,
        f"SELECT i.* FROM library_items i WHERE {where} ORDER BY RANDOM() LIMIT 1",
        args,
    )
    if not row:
        return None
    _attach_facets(conn, [row])
    return serialize_item(row)


def list_items(
    conn: sqlite3.Connection,
    *,
    kind: str = "",
    query: str = "",
    category: str = "",
    facets: Iterable[tuple[str, str]] = (),
    favorite: bool | None = None,
    depth_only: bool = False,
    limit: int = 60,
    offset: int = 0,
    include_nsfw: bool = True,
) -> dict[str, Any]:
    where, args = _scope(
        kind=kind,
        query=query,
        favorite=favorite,
        selected=facets,
        depth_only=depth_only,
        include_nsfw=include_nsfw,
    )
    if category:
        where += (
            " AND EXISTS (SELECT 1 FROM library_facets f WHERE f.item_id = i.id"
            " AND f.level <= 2 AND f.value = ?)"
        )
        args.append(category)
    total = db.scalar(conn, f"SELECT COUNT(*) FROM library_items i WHERE {where}", args) or 0
    rows = db.rows(
        conn,
        f"SELECT i.* FROM library_items i WHERE {where} "
        "ORDER BY i.favorite DESC, i.created_at DESC, i.title LIMIT ? OFFSET ?",
        [*args, limit, offset],
    )
    _attach_facets(conn, rows)
    return {
        "items": [serialize_item(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def _tree_for(
    conn: sqlite3.Connection,
    kind: str,
    query: str,
    favorite: bool | None,
    selected: Iterable[tuple[str, str]],
    active_kind: str = "",
    include_nsfw: bool = True,
) -> dict[str, Any]:
    fields = taxonomy.FIELDS.get(kind, taxonomy.GENERIC_FIELDS)
    top_field = fields[0][0]
    sub_field = fields[1][0] if len(fields) > 1 else ""
    # Counts ignore the currently selected kind on purpose: the sidebar keeps
    # every type visible so switching types never makes a whole branch vanish.
    # Facet selections only narrow the kind they belong to, so other types stay
    # usable as navigation targets while a filter is active.
    scoped = list(selected) if (not active_kind or kind == active_kind) else []
    where, args = _scope(
        query=query,
        favorite=favorite,
        selected=scoped,
        exclude={top_field, sub_field},
        include_nsfw=include_nsfw,
    )
    where = f"{where} AND i.kind = ?"
    args = [*args, kind]

    top = db.rows(
        conn,
        f"""
        SELECT f.value AS value, COUNT(*) AS count
        FROM library_items i
        JOIN library_facets f ON f.item_id = i.id AND f.level = 1 AND f.field = ?
        WHERE {where}
        GROUP BY f.value
        ORDER BY count DESC, f.value
        """,
        [top_field, *args],
    )
    children: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if sub_field:
        pairs = db.rows(
            conn,
            f"""
            SELECT a.value AS parent, b.value AS child, COUNT(DISTINCT i.id) AS count
            FROM library_items i
            JOIN library_facets a ON a.item_id = i.id AND a.level = 1 AND a.field = ?
            JOIN library_facets b ON b.item_id = i.id AND b.level = 2 AND b.field = ?
            WHERE {where}
            GROUP BY a.value, b.value
            ORDER BY count DESC, b.value
            """,
            [top_field, sub_field, *args],
        )
        for pair in pairs:
            children[pair["parent"]].append({"value": pair["child"], "count": pair["count"]})

    return {
        "kind": kind,
        "label": taxonomy.KIND_LABEL.get(kind, kind),
        "count": sum(int(item["count"]) for item in top),
        "fields": {"level1": top_field, "level2": sub_field},
        "children": [
            {"value": item["value"], "count": item["count"], "children": children.get(item["value"], [])}
            for item in top
        ],
    }


def _dims_for(
    conn: sqlite3.Connection,
    kind: str,
    query: str,
    favorite: bool | None,
    selected: Iterable[tuple[str, str]],
    include_nsfw: bool = True,
) -> list[dict[str, Any]]:
    dims: list[dict[str, Any]] = []
    for name, level in taxonomy.FIELDS.get(kind, taxonomy.GENERIC_FIELDS):
        if level < 3:
            continue
        where, args = _scope(
            kind=kind,
            query=query,
            favorite=favorite,
            selected=selected,
            exclude={name},
            include_nsfw=include_nsfw,
        )
        values = db.rows(
            conn,
            f"""
            SELECT f.value AS value, COUNT(*) AS count
            FROM library_items i
            JOIN library_facets f ON f.item_id = i.id AND f.level = ? AND f.field = ?
            WHERE {where}
            GROUP BY f.value
            ORDER BY count DESC, f.value
            """,
            [level, name, *args],
        )
        if values:
            dims.append({"field": name, "values": values})
    return dims


def facets(
    conn: sqlite3.Connection,
    *,
    kind: str = "",
    query: str = "",
    favorite: bool | None = None,
    selected: Iterable[tuple[str, str]] = (),
    include_nsfw: bool = True,
) -> dict[str, Any]:
    selected = list(selected)
    where, args = _scope(
        kind=kind,
        query=query,
        favorite=favorite,
        selected=selected,
        include_nsfw=include_nsfw,
    )
    total = db.scalar(conn, f"SELECT COUNT(*) FROM library_items i WHERE {where}", args) or 0
    favorites_where, favorites_args = _scope(
        kind=kind,
        query=query,
        favorite=None,
        selected=selected,
        include_nsfw=include_nsfw,
    )
    favorites = db.scalar(
        conn,
        f"SELECT COUNT(*) FROM library_items i WHERE {favorites_where} AND i.favorite = 1",
        favorites_args,
    ) or 0
    tree_where, tree_args = _scope(
        query=query, favorite=favorite, include_nsfw=include_nsfw
    )
    tree_kinds = db.rows(
        conn,
        f"SELECT i.kind AS kind, COUNT(*) AS count FROM library_items i "
        f"WHERE {tree_where} GROUP BY i.kind ORDER BY count DESC",
        tree_args,
    )
    tree = [
        _tree_for(
            conn,
            row["kind"],
            query,
            favorite,
            selected,
            active_kind=kind,
            include_nsfw=include_nsfw,
        )
        for row in tree_kinds
    ]
    dims = (
        _dims_for(conn, kind, query, favorite, selected, include_nsfw=include_nsfw)
        if kind
        else []
    )
    hidden = 0
    if not include_nsfw:
        hidden_where, hidden_args = _scope(
            kind=kind, query=query, favorite=favorite, selected=selected
        )
        hidden = db.scalar(
            conn,
            f"SELECT COUNT(*) FROM library_items i WHERE {hidden_where} AND i.nsfw = 1",
            hidden_args,
        ) or 0
    visible_total = db.scalar(
        conn,
        "SELECT COUNT(*) FROM library_items" + ("" if include_nsfw else " WHERE nsfw = 0"),
    ) or 0
    depth_where = "has_depth = 1" + ("" if include_nsfw else " AND nsfw = 0")
    depth_total = db.scalar(conn, f"SELECT COUNT(*) FROM library_items WHERE {depth_where}") or 0
    return {
        "kinds": [{"kind": row["kind"], "count": row["count"], "label": taxonomy.KIND_LABEL.get(row["kind"], row["kind"])} for row in tree_kinds],
        "tree": tree,
        "dims": dims,
        "total": total,
        "favorite": favorites,
        "nsfw_hidden": hidden,
        "visible_total": visible_total,
        "depth_total": depth_total,
    }


def categories(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Legacy flat list, kept for older clients."""

    return db.rows(
        conn,
        "SELECT category, COUNT(*) AS count FROM library_items WHERE category <> '' "
        "GROUP BY category ORDER BY count DESC LIMIT 60",
    )


# ── reclassification ──────────────────────────────────────────────────────


def _source_entries(rows: list[dict]) -> dict[str, dict[str, dict]]:
    """Load source JSON for every indexed gallery checkout, keyed by external id."""

    cache: dict[str, dict[str, dict]] = {}
    for source in {row["source"] for row in rows}:
        if not source.startswith("pose-gallery:"):
            continue
        base = Path(source.removeprefix("pose-gallery:"))
        data_dir = base / "data"
        if not data_dir.exists():
            continue
        mapping: dict[str, dict] = {}
        for kind, filename in GALLERY_FILES:
            for entry in _load_json(data_dir / filename):
                if not entry.get("id"):
                    continue
                if filename == "costume-shisei-zh.json":
                    for view in _shisei_views(entry):
                        mapping[f"costume-view:{entry['id']}:{view.get('id')}"] = {
                            **entry,
                            "服装名称": f"{entry.get('服装名称') or entry.get('id')} · {view.get('label') or ''}".strip(" ·"),
                            "视角": view.get("label") or "",
                            "id": f"{entry['id']}:{view.get('id')}",
                        }
                else:
                    mapping[f"{kind}:{entry['id']}"] = entry
        cache[source] = mapping
    return cache


def _classify_row(
    row: dict,
    entries: dict[str, dict[str, dict]],
    previous: dict[str, list[str]] | None = None,
) -> taxonomy.Classification:
    entry = entries.get(row["source"], {}).get(row.get("external_id") or "")
    if entry:
        return taxonomy.classify_entry(row["kind"], entry)

    known = previous or {}

    def first(field: str) -> str:
        values = known.get(field) or []
        return values[0] if values else ""

    meta = db.loads(row.get("meta"), {})
    ident = row.get("external_id") or ""
    if row["kind"] == "pose":
        return taxonomy.classify_pose(
            {
                "体系": meta.get("series") or first("构图") or row.get("category"),
                "分类": first("姿势分类"),
                "角度": meta.get("angle") or first("角度"),
                "姿势名称": row.get("title"),
                "id": ident,
            }
        )
    if row["kind"] == "costume":
        return taxonomy.classify_costume(
            {
                "分类": first("风格") or row.get("category"),
                "服装名称": row.get("title"),
                "标签": known.get("单品") or [],
                "id": ident,
            }
        )
    if row["kind"] == "portrait":
        title = row.get("title") or ""
        head = title.split("・", 1)[0] if "・" in title else ""
        return taxonomy.classify_portrait(
            {
                "分区": first("分区") or row.get("category"),
                "发长": first("发长") or (head if head in {"短发", "中发", "中长发", "长发"} else ""),
                "标题": title,
                "id": ident,
            }
        )
    if row["kind"] == "work":
        return taxonomy.classify_work(row.get("title") or "")
    return taxonomy.classify_folder(row.get("subtitle") or row.get("title") or "", row.get("title") or "")


def _facets_by_item(conn: sqlite3.Connection) -> dict[str, dict[str, list[str]]]:
    grouped: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for facet in db.rows(conn, "SELECT item_id, field, value FROM library_facets ORDER BY level"):
        grouped[facet["item_id"]][facet["field"]].append(facet["value"])
    return grouped


def rebuild_taxonomy(conn: sqlite3.Connection) -> dict[str, Any]:
    """Recompute category paths/facets/search text for every indexed item."""

    rows = db.rows(conn, "SELECT * FROM library_items")
    entries = _source_entries(rows)
    previous = _facets_by_item(conn)
    conn.execute("DELETE FROM library_facets")
    updates: list[tuple] = []
    facet_rows: list[tuple] = []
    for row in rows:
        classification = _classify_row(row, entries, previous.get(row["id"]))
        updates.append(
            (
                classification.category[:120],
                classification.category_path[:300],
                classification.tags[:500],
                classification.search_text[:2000],
                int(classification.nsfw),
                row["id"],
            )
        )
        facet_rows.extend(
            (row["id"], field, value, int(level))
            for field, value, level in classification.facets
        )
    conn.executemany(
        "UPDATE library_items SET category = ?, category_path = ?, tags = ?, search_text = ?,"
        " nsfw = ? WHERE id = ?",
        updates,
    )
    conn.executemany(
        "INSERT OR IGNORE INTO library_facets (item_id, field, value, level) VALUES (?, ?, ?, ?)",
        facet_rows,
    )
    conn.execute(
        "INSERT INTO app_meta(k, v) VALUES ('library_taxonomy', ?) "
        "ON CONFLICT(k) DO UPDATE SET v = excluded.v",
        (taxonomy.TAXONOMY_VERSION,),
    )
    return {"items": len(updates), "facets": len(facet_rows)}


def ensure_taxonomy(conn: sqlite3.Connection) -> dict[str, Any] | None:
    """One-time (per rules version) backfill for libraries imported by v1/v2."""

    total = db.scalar(conn, "SELECT COUNT(*) FROM library_items") or 0
    if not total:
        return None
    version = db.scalar(conn, "SELECT v FROM app_meta WHERE k = 'library_taxonomy'")
    stale = db.scalar(conn, "SELECT COUNT(*) FROM library_items WHERE search_text = ''") or 0
    if version == taxonomy.TAXONOMY_VERSION and not stale:
        return None
    return rebuild_taxonomy(conn)


def ensure_variants(conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Backfill group keys and pose depth companions for libraries imported before v6."""

    if db.scalar(conn, "SELECT v FROM app_meta WHERE k = 'library_variants'") == "2":
        return None
    rows = db.rows(
        conn,
        "SELECT id, source, external_id, kind, group_key, variant_label, depth_path, meta "
        "FROM library_items WHERE kind = 'pose' OR group_key = '' "
        "OR (kind = 'pose' AND depth_path IS NULL)",
    )
    changed = depth_found = 0
    for row in rows:
        updates: dict[str, Any] = {}
        meta = db.loads(row.get("meta"), {})
        if row["kind"] == "pose":
            series = str(meta.get("series") or "")
            code = str(meta.get("code") or "")
            desired = f"pose:{series}:{code}" if code and series else (f"pose:{code}" if code else (row.get("external_id") or row["id"]))
            if desired != row.get("group_key"):
                updates["group_key"] = desired
        elif not row.get("group_key"):
            updates["group_key"] = row.get("external_id") or row["id"]
        if row["kind"] == "pose" and not row.get("variant_label") and meta.get("angle"):
            updates["variant_label"] = str(meta.get("angle"))
        if row["kind"] == "pose" and not row.get("depth_path"):
            source = str(row.get("source") or "")
            if source.startswith("pose-gallery:"):
                base = Path(source.removeprefix("pose-gallery:"))
                pose_id = str(row.get("external_id") or "")
                if pose_id.startswith("pose:"):
                    pose_id = pose_id[5:]
                if base.exists():
                    depth, thumb = _depth_files(base, pose_id)
                    if depth and is_allowed(depth):
                        updates["depth_path"] = str(depth)
                        updates["has_depth"] = 1
                        if thumb and is_allowed(thumb):
                            updates["depth_thumb_path"] = str(thumb)
                        depth_found += 1
        if not updates:
            continue
        columns = ", ".join(f"{key} = ?" for key in updates)
        conn.execute(
            f"UPDATE library_items SET {columns} WHERE id = ?",
            (*updates.values(), row["id"]),
        )
        changed += 1
    conn.execute(
        "INSERT INTO app_meta(k, v) VALUES ('library_variants', '2') "
        "ON CONFLICT(k) DO UPDATE SET v = excluded.v"
    )
    return {"items": changed, "depth": depth_found}


def file_for(
    conn: sqlite3.Connection, item_id: str, prefer_thumb: bool, variant: str = "base"
) -> tuple[Path, str]:
    item = db.one(conn, "SELECT * FROM library_items WHERE id = ?", (item_id,))
    if not item:
        raise FileNotFoundError("素材不存在")
    candidates: list[Path] = []
    if variant == "depth":
        if prefer_thumb and item.get("depth_thumb_path"):
            candidates.append(Path(item["depth_thumb_path"]))
        if item.get("depth_path"):
            candidates.append(Path(item["depth_path"]))
    else:
        if prefer_thumb and item.get("thumb_path"):
            candidates.append(Path(item["thumb_path"]))
        candidates.append(Path(item["image_path"]))
    for candidate in candidates:
        if candidate.exists() and is_allowed(candidate):
            return candidate.resolve(), "image"
    raise FileNotFoundError("素材文件已不存在或被移动到允许目录之外")


def delete_item(conn: sqlite3.Connection, item_id: str) -> None:
    conn.execute("DELETE FROM library_items WHERE id = ?", (item_id,))


def collect_files(paths: Iterable[str]) -> list[Path]:
    result: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_file():
            result.append(path)
    return result


__all__ = [
    "add_asset_reference",
    "add_uploaded",
    "allowed_roots",
    "categories",
    "delete_item",
    "ensure_taxonomy",
    "ensure_variants",
    "facets",
    "file_for",
    "import_folder",
    "import_pose_gallery",
    "item_facets",
    "item_variants",
    "list_items",
    "random_item",
    "rebuild_taxonomy",
    "resolve_allowed",
    "serialize_item",
    "storage",
    "taxonomy",
]
