"""Prompt library CRUD and prompt enhancement (LLM or local rules)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Query

from .. import db
from ..core import prompt_enhance, prompt_rewrite
from ..errors import Conflict, NotFound
from .deps import get_conn
from .schemas import EnhanceIn, PromptIn

router = APIRouter(prefix="/api", tags=["prompts"])

CATEGORIES = {"quality", "camera", "lighting", "style", "custom"}


def serialize(row: dict) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "category": row["category"],
        "text": row["text"],
        "negative": row["negative"],
        "tags": row["tags"],
        "favorite": bool(row["favorite"]),
        "builtin": bool(row["builtin"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


@router.get("/prompts")
def list_prompts(
    category: str = Query(default="", max_length=20),
    q: str = Query(default="", max_length=200),
    favorite: bool | None = None,
    conn: sqlite3.Connection = Depends(get_conn),
):
    clauses: list[str] = []
    args: list = []
    if category:
        clauses.append("category = ?")
        args.append(category)
    if favorite is not None:
        clauses.append("favorite = ?")
        args.append(int(favorite))
    if q:
        clauses.append("(title LIKE ? OR text LIKE ? OR tags LIKE ?)")
        like = f"%{q}%"
        args.extend([like, like, like])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = db.rows(
        conn,
        f"SELECT * FROM prompts {where} ORDER BY favorite DESC, builtin DESC, created_at DESC",
        args,
    )
    return {"items": [serialize(row) for row in rows], "total": len(rows)}


@router.post("/prompts")
def create_prompt(data: PromptIn, conn: sqlite3.Connection = Depends(get_conn)):
    prompt_id = db.new_id()
    stamp = db.now()
    conn.execute(
        "INSERT INTO prompts (id, title, category, text, negative, tags, favorite, builtin, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
        (
            prompt_id,
            data.title.strip(),
            data.category,
            data.text.strip(),
            data.negative.strip(),
            data.tags.strip(),
            int(data.favorite),
            stamp,
            stamp,
        ),
    )
    return serialize(db.one(conn, "SELECT * FROM prompts WHERE id = ?", (prompt_id,)))


@router.put("/prompts/{prompt_id}")
def update_prompt(
    prompt_id: str, data: PromptIn, conn: sqlite3.Connection = Depends(get_conn)
):
    row = db.one(conn, "SELECT * FROM prompts WHERE id = ?", (prompt_id,))
    if not row:
        raise NotFound("提示词不存在")
    if row["builtin"]:
        raise Conflict("内置提示词不可编辑")
    conn.execute(
        "UPDATE prompts SET title=?, category=?, text=?, negative=?, tags=?, favorite=?, updated_at=? "
        "WHERE id=?",
        (
            data.title.strip(),
            data.category,
            data.text.strip(),
            data.negative.strip(),
            data.tags.strip(),
            int(data.favorite),
            db.now(),
            prompt_id,
        ),
    )
    return serialize(db.one(conn, "SELECT * FROM prompts WHERE id = ?", (prompt_id,)))


@router.post("/prompts/{prompt_id}/favorite")
def toggle_favorite(prompt_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    row = db.one(conn, "SELECT * FROM prompts WHERE id = ?", (prompt_id,))
    if not row:
        raise NotFound("提示词不存在")
    conn.execute(
        "UPDATE prompts SET favorite = ?, updated_at = ? WHERE id = ?",
        (0 if row["favorite"] else 1, db.now(), prompt_id),
    )
    return serialize(db.one(conn, "SELECT * FROM prompts WHERE id = ?", (prompt_id,)))


@router.delete("/prompts/{prompt_id}")
def delete_prompt(prompt_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    row = db.one(conn, "SELECT * FROM prompts WHERE id = ?", (prompt_id,))
    if not row:
        raise NotFound("提示词不存在")
    if row["builtin"]:
        raise Conflict("内置提示词不可删除")
    conn.execute("DELETE FROM prompts WHERE id = ?", (prompt_id,))
    return {"ok": True}


@router.post("/prompt/enhance")
async def enhance_prompt(data: EnhanceIn, conn: sqlite3.Connection = Depends(get_conn)):
    payload = data.model_dump()
    if payload.pop("mode") == "llm":
        return await prompt_rewrite.rewrite(conn, payload)
    return prompt_enhance.enhance(payload)
