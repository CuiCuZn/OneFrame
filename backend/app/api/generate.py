"""Generation entry points, prompt compiler and static catalog."""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends

from .. import db
from ..core import prompt as prompt_engine
from ..core import router as routing
from ..errors import Conflict
from ..providers import catalog as protocol_catalog
from .deps import get_conn
from .schemas import CompileIn, GenerateIn

router = APIRouter(prefix="/api", tags=["generate"])

SIZES = [
    "1024x1024", "1024x1536", "1536x1024", "1280x720", "720x1280",
    "1920x1080", "1080x1920", "2048x2048", "2560x1440", "1440x2560",
]
ASPECTS = ["1:1", "4:3", "3:4", "16:9", "9:16"]
DURATIONS = [4, 5, 6, 8, 10, 12]
RESOLUTIONS = ["480p", "720p", "1080p"]


@router.get("/catalog")
def catalog(conn: sqlite3.Connection = Depends(get_conn)):
    settings = db.settings_all(conn)
    return {
        "protocols": protocol_catalog(),
        "styles": prompt_engine.style_catalog(),
        "sizes": SIZES,
        "aspects": ASPECTS,
        "image_resolutions": ["1K", "2K", "4K"],
        "durations": DURATIONS,
        "resolutions": RESOLUTIONS,
        "roles": [
            {"id": "character", "name": "人物", "hint": "保持脸型、发型与气质"},
            {"id": "costume", "name": "服装", "hint": "提取整套穿搭与配饰"},
            {"id": "pose", "name": "姿势", "hint": "只取姿态与构图"},
            {"id": "style", "name": "风格", "hint": "借色彩、光影与质感"},
            {"id": "reference", "name": "参考", "hint": "作为补充信息"},
        ],
        "features": routing.FEATURE_LABELS,
        "defaults": {
            "negative": prompt_engine.DEFAULT_NEGATIVE,
            "image_model": settings.get("default_image_model", ""),
            "video_model": settings.get("default_video_model", ""),
        },
    }


@router.post("/prompt/compile")
def compile_prompt(data: CompileIn):
    return prompt_engine.compile_recipe(data.model_dump())


@router.post("/generate")
def generate(data: GenerateIn, conn: sqlite3.Connection = Depends(get_conn)):
    row = db.one(conn, "SELECT * FROM models WHERE id = ?", (data.model_id,))
    if not row:
        raise Conflict("请选择一个可用模型")
    model = routing.load_model(conn, data.model_id)
    prompt_text = data.prompt.strip()
    style = prompt_engine.STYLE_BY_ID.get(data.style)
    if style and style.get("zh") and style["zh"] not in prompt_text:
        prompt_text = f"{prompt_text}\n风格：{style['zh']}"
    req = routing.build_request(
        upstream_model=model["upstream_model"],
        prompt=prompt_text,
        negative=data.negative.strip(),
        refs=[],
        count=data.count,
        params=data.params,
    )
    routing.check(conn, model, req)
    estimate = routing.estimate(model, req)
    target = routing.target(model)
    job_id = db.new_id()
    snapshot: dict[str, Any] = {
        "prompt": prompt_text,
        "negative": data.negative.strip(),
        "count": data.count,
        "params": data.params,
        "refs": [ref.model_dump() for ref in data.refs],
        "model_id": data.model_id,
        "model_name": row["name"],
        "channel_id": model["channel_id"],
        "channel_name": model.get("channel_name", ""),
        "upstream_model": model["upstream_model"],
        "modality": row["modality"],
        "style": data.style,
        "source": data.source,
    }
    conn.execute(
        "INSERT INTO jobs(id, model_id, model_name, channel_name, modality, request, status, stage, channel_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'queued', '排队中', ?, ?)",
        (
            job_id,
            data.model_id,
            row["name"],
            model.get("channel_name") or "",
            row["modality"],
            db.dumps(snapshot),
            model["channel_id"],
            db.now(),
        ),
    )
    return {
        "job_id": job_id,
        "estimate": estimate,
        "modality": row["modality"],
        "target": target.public(),
    }


@router.get("/estimate")
def estimate(
    model_id: str,
    count: int = 1,
    duration: float = 0,
    conn: sqlite3.Connection = Depends(get_conn),
):
    model = routing.load_model(conn, model_id)
    req = routing.build_request(
        upstream_model=model["upstream_model"],
        prompt="",
        negative="",
        refs=[],
        count=count,
        params={"duration": duration} if duration else {},
    )
    return routing.estimate(model, req)
