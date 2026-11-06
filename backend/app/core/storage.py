"""Media storage: content-addressed-ish files, thumbnails, video posters."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from .. import config

MEDIA_TOOL_CACHE: dict[str, str | None] = {}


def media_tool(name: str) -> str | None:
    """Locate ffmpeg/ffprobe even when the interpreter's Scripts dir is off PATH."""

    if name in MEDIA_TOOL_CACHE:
        return MEDIA_TOOL_CACHE[name]
    found = shutil.which(name)
    if not found:
        for candidate in (
            Path(sys.executable).parent / f"{name}.exe",
            Path(sys.executable).parent / "Scripts" / f"{name}.exe",
            Path("C:/ffmpeg/bin") / f"{name}.exe",
        ):
            if candidate.exists():
                found = str(candidate)
                break
    MEDIA_TOOL_CACHE[name] = found
    return found

IMAGE_EXTS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/avif": ".avif",
}


def _month_dir(root: Path) -> Path:
    now = datetime.now(UTC)
    path = root / f"{now:%Y}" / f"{now:%m}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def sniff_mime(data: bytes, fallback: str = "application/octet-stream") -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:8] == b"ftyp":
        return "video/mp4"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return fallback


def _thumb_path_for(source: Path) -> Path:
    rel = source.relative_to(config.DATA_DIR)
    target = config.THUMB_DIR / rel.with_suffix(".webp")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def make_image_thumb(source: Path, size: int = 640) -> Path:
    target = _thumb_path_for(source)
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((size, size), Image.LANCZOS)
        image.save(target, "WEBP", quality=84, method=4)
    return target


def video_poster(source: Path, at: float = 0.6) -> Path:
    target = _thumb_path_for(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = media_tool("ffmpeg")
    if not ffmpeg:
        return Path()
    command = [
        ffmpeg, "-y", "-ss", str(at), "-i", str(source), "-frames:v", "1",
        "-vf", "scale='min(640,iw)':-2", "-q:v", "3", str(target.with_suffix(".jpg")),
    ]
    try:
        subprocess.run(command, capture_output=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        return Path()
    jpg = target.with_suffix(".jpg")
    if not jpg.exists():
        try:
            subprocess.run(
                [ffmpeg, "-y", "-i", str(source), "-frames:v", "1",
                 "-vf", "scale='min(640,iw)':-2", str(jpg)],
                capture_output=True, timeout=60, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return Path()
    if not jpg.exists():
        return Path()
    with Image.open(jpg) as image:
        image = image.convert("RGB")
        image.save(target, "WEBP", quality=84, method=4)
    jpg.unlink(missing_ok=True)
    return target


def probe_video(source: Path) -> dict[str, Any]:
    ffprobe = media_tool("ffprobe")
    if not ffprobe:
        return {}
    command = [
        ffprobe, "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(source),
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=30, check=False)
        payload = json.loads(result.stdout or b"{}")
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}
    duration = 0.0
    width = height = 0
    try:
        duration = float(payload.get("format", {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    for stream in payload.get("streams", []):
        if stream.get("codec_type") == "video":
            width = int(stream.get("width") or 0)
            height = int(stream.get("height") or 0)
            break
    return {"duration_ms": int(duration * 1000), "width": width, "height": height}


def save_output(data: bytes, kind: str, mime: str | None = None) -> dict[str, Any]:
    mime = mime or sniff_mime(data)
    if kind == "image" and not mime.startswith("image/"):
        mime = sniff_mime(data, "image/png")
    ext = IMAGE_EXTS.get(mime) or (".mp4" if kind == "video" else ".png")
    folder = _month_dir(config.MEDIA_DIR)
    digest = hashlib.sha256(data).hexdigest()[:16]
    path = folder / f"{datetime.now(UTC):%d}-{digest}-{uuid.uuid4().hex[:6]}{ext}"
    path.write_bytes(data)

    record: dict[str, Any] = {
        "path": path.relative_to(config.DATA_DIR).as_posix(),
        "bytes": len(data),
        "mime": mime,
        "width": None,
        "height": None,
        "duration_ms": None,
        "thumb_path": None,
    }
    if kind == "image" or mime.startswith("image/"):
        try:
            with Image.open(io.BytesIO(data)) as image:
                image = ImageOps.exif_transpose(image)
                record["width"], record["height"] = image.size
            record["thumb_path"] = make_image_thumb(path).relative_to(config.DATA_DIR).as_posix()
        except Exception:  # pragma: no cover - defensive for exotic formats
            pass
    else:
        info = probe_video(path)
        record.update({k: v for k, v in info.items() if v})
        poster = video_poster(path)
        if poster and poster.exists():
            record["thumb_path"] = poster.relative_to(config.DATA_DIR).as_posix()
    return record


def save_upload(filename: str, data: bytes, mime: str | None = None) -> dict[str, Any]:
    mime = mime or sniff_mime(data)
    digest = hashlib.sha256(data).hexdigest()[:12]
    suffix = Path(filename or "").suffix.lower() or IMAGE_EXTS.get(mime, ".bin")
    folder = config.UPLOAD_DIR / f"{datetime.now(UTC):%Y%m}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{digest}-{uuid.uuid4().hex[:6]}{suffix}"
    path.write_bytes(data)
    record: dict[str, Any] = {
        "path": path.relative_to(config.DATA_DIR).as_posix(),
        "bytes": len(data),
        "mime": mime,
        "width": None,
        "height": None,
        "thumb_path": None,
        "kind": "image",
    }
    if mime.startswith("image/"):
        try:
            with Image.open(io.BytesIO(data)) as image:
                image = ImageOps.exif_transpose(image)
                record["width"], record["height"] = image.size
            record["thumb_path"] = make_image_thumb(path).relative_to(config.DATA_DIR).as_posix()
        except Exception:
            pass
    elif mime.startswith("video/"):
        record["kind"] = "video"
        info = probe_video(path)
        record.update({k: v for k, v in info.items() if v})
        poster = video_poster(path)
        if poster and poster.exists():
            record["thumb_path"] = poster.relative_to(config.DATA_DIR).as_posix()
    return record


def resolve_media(rel_path: str) -> Path | None:
    """Return an absolute path only when it stays below DATA_DIR."""
    if not rel_path:
        return None
    candidate = (config.DATA_DIR / rel_path).resolve() if not Path(rel_path).is_absolute() else Path(rel_path).resolve()
    try:
        candidate.relative_to(config.DATA_DIR)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def delete_files(*paths: str | None) -> None:
    for rel in paths:
        if not rel:
            continue
        target = resolve_media(rel)
        if target and target.exists():
            try:
                target.unlink()
            except OSError:
                pass


def disk_usage() -> dict[str, int]:
    total = 0
    media = 0
    for path in config.DATA_DIR.rglob("*"):
        if path.is_file():
            try:
                size = path.stat().st_size
            except OSError:
                continue
            total += size
            if config.MEDIA_DIR in path.parents:
                media += size
    return {"total": total, "media": media}


def free_space(path: Path = config.DATA_DIR) -> int:
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return 0
