"""Runtime configuration for OneFrame.

Everything is local-first: a single SQLite file, a media directory and a
Fernet master key live under ``data/`` unless overridden by env vars.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("ONEFRAME_DATA", BASE_DIR / "data")).resolve()
MEDIA_DIR = DATA_DIR / "media"
UPLOAD_DIR = DATA_DIR / "uploads"
THUMB_DIR = DATA_DIR / "thumbs"
EXPORT_DIR = DATA_DIR / "exports"
DB_PATH = Path(os.environ.get("ONEFRAME_DB", DATA_DIR / "oneframe.db"))
SECRET_KEY_PATH = DATA_DIR / "secret.key"
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"

HOST = os.environ.get("ONEFRAME_HOST", "127.0.0.1")
PORT = int(os.environ.get("ONEFRAME_PORT", "8787"))

# Concurrency in the local job runner.
IMAGE_WORKERS = int(os.environ.get("ONEFRAME_IMAGE_WORKERS", "3"))
VIDEO_WORKERS = int(os.environ.get("ONEFRAME_VIDEO_WORKERS", "2"))

# Upload limits (bytes).
MAX_UPLOAD_BYTES = int(os.environ.get("ONEFRAME_MAX_UPLOAD", str(25 * 1024 * 1024)))
MAX_ASSET_BYTES = int(os.environ.get("ONEFRAME_MAX_ASSET", str(512 * 1024 * 1024)))

# Library indexing may only read below these roots (plus DATA_DIR).
LIBRARY_ROOTS = [
    Path(p).resolve()
    for p in os.environ.get("ONEFRAME_LIBRARY_ROOTS", "").split(os.pathsep)
    if p.strip()
]

APP_NAME = "OneFrame"
APP_VERSION = "1.0.0"

DEFAULT_SETTINGS = {
    "theme": "dark",
    "default_image_model": "",
    "default_video_model": "",
    "auto_download": "0",
    "save_prompt_history": "1",
    "max_parallel_image": str(IMAGE_WORKERS),
    "max_parallel_video": str(VIDEO_WORKERS),
    "prompt_language": "zh",
    "sfw": "0",
    "library_nsfw": "0",
    "library_roots": "",
}


def ensure_dirs() -> None:
    for path in (DATA_DIR, MEDIA_DIR, UPLOAD_DIR, THUMB_DIR, EXPORT_DIR):
        path.mkdir(parents=True, exist_ok=True)

