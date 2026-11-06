"""Usage insights, settings and system info."""

from __future__ import annotations

import shutil
import sqlite3
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends

from .. import config, db
from ..core import library, storage
from .deps import get_conn
from .schemas import SettingsIn

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/stats")
def stats(conn: sqlite3.Connection = Depends(get_conn)):
    since = (datetime.now(UTC) - timedelta(days=30)).isoformat(timespec="seconds")
    assets_total = db.scalar(conn, "SELECT COUNT(*) FROM assets") or 0
    by_kind = {
        row["kind"]: row["count"]
        for row in db.rows(conn, "SELECT kind, COUNT(*) AS count FROM assets GROUP BY kind")
    }
    jobs_total = db.scalar(conn, "SELECT COUNT(*) FROM jobs") or 0
    succeeded = db.scalar(conn, "SELECT COUNT(*) FROM jobs WHERE status='succeeded'") or 0
    failed = db.scalar(conn, "SELECT COUNT(*) FROM jobs WHERE status='failed'") or 0
    today = datetime.now(UTC).date().isoformat()
    jobs_today = db.scalar(
        conn, "SELECT COUNT(*) FROM jobs WHERE substr(created_at,1,10) = ?", (today,)
    ) or 0
    spend = db.scalar(conn, "SELECT COALESCE(SUM(price),0) FROM jobs WHERE status='succeeded'") or 0
    spend_30d = db.scalar(
        conn,
        "SELECT COALESCE(SUM(price),0) FROM jobs WHERE status='succeeded' AND created_at >= ?",
        (since,),
    ) or 0
    daily_rows = db.rows(
        conn,
        """
        SELECT substr(created_at,1,10) AS day, COUNT(*) AS jobs,
               SUM(CASE WHEN status='succeeded' THEN 1 ELSE 0 END) AS ok,
               COALESCE(SUM(CASE WHEN status='succeeded' THEN price ELSE 0 END),0) AS spend
        FROM jobs WHERE created_at >= ? GROUP BY day ORDER BY day
        """,
        ((datetime.now(UTC) - timedelta(days=13)).isoformat(timespec="seconds"),),
    )
    days = {row["day"]: row for row in daily_rows}
    series = []
    for offset in range(13, -1, -1):
        day = (datetime.now(UTC) - timedelta(days=offset)).date().isoformat()
        row = days.get(day, {})
        series.append(
            {
                "day": day,
                "jobs": row.get("jobs", 0),
                "ok": row.get("ok", 0),
                "spend": round(float(row.get("spend", 0)), 4),
            }
        )
    top_models = db.rows(
        conn,
        "SELECT model_name, COUNT(*) AS count FROM assets WHERE model_name <> '' "
        "GROUP BY model_name ORDER BY count DESC LIMIT 6",
    )
    channels = db.rows(
        conn,
        """
        SELECT c.id, c.name, c.protocol,
               (SELECT COUNT(*) FROM channel_keys k WHERE k.channel_id = c.id) AS keys,
               (SELECT COUNT(*) FROM channel_keys k WHERE k.channel_id = c.id AND k.status='ok') AS ok_keys,
               (SELECT COUNT(*) FROM jobs j WHERE j.channel_id = c.id) AS jobs,
               (SELECT COALESCE(SUM(j.price),0) FROM jobs j WHERE j.channel_id = c.id AND j.status='succeeded') AS spend
        FROM channels c ORDER BY jobs DESC
        """,
    )
    return {
        "assets": {"total": assets_total, "by_kind": by_kind,
                   "favorite": db.scalar(conn, "SELECT COUNT(*) FROM assets WHERE favorite=1") or 0},
        "jobs": {
            "total": jobs_total,
            "today": jobs_today,
            "succeeded": succeeded,
            "failed": failed,
            "success_rate": round(succeeded / max(succeeded + failed, 1) * 100, 1),
        },
        "spend": {"total": round(float(spend), 4), "last_30d": round(float(spend_30d), 4)},
        "series": series,
        "top_models": top_models,
        "channels": channels,
        "disk": storage.disk_usage(),
    }


@router.get("/system")
def system(conn: sqlite3.Connection = Depends(get_conn)):
    usage = shutil.disk_usage(config.DATA_DIR)
    storage_usage = storage.disk_usage()
    return {
        "name": config.APP_NAME,
        "version": config.APP_VERSION,
        "data_dir": str(config.DATA_DIR),
        "db_path": str(config.DB_PATH),
        "media_dir": str(config.MEDIA_DIR),
        "free_bytes": usage.free,
        "total_bytes": usage.total,
        "data_bytes": storage_usage["total"],
        "media_bytes": storage_usage["media"],
        "ffmpeg": shutil.which("ffmpeg") or "",
        "library_roots": [str(path) for path in library.allowed_roots()],
        "workers": {"image": config.IMAGE_WORKERS, "video": config.VIDEO_WORKERS},
    }


@router.get("/settings")
def get_settings(conn: sqlite3.Connection = Depends(get_conn)):
    return db.settings_all(conn)


@router.put("/settings")
def put_settings(data: SettingsIn, conn: sqlite3.Connection = Depends(get_conn)):
    allowed = set(config.DEFAULT_SETTINGS)
    for key, value in data.values.items():
        if key in allowed:
            db.set_setting(conn, key, value)
    return db.settings_all(conn)

