"""Model resolution: one selectable model == one vendor + one upstream model.

There is deliberately no cross-vendor fallback.  A model either runs on its own
channel or fails; the only automatic retry is trying another key of the *same*
channel when the vendor explicitly rejects the credential or rate-limits it.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .. import db
from ..errors import ProviderError, Unsupported
from ..providers import GenRequest, RefImage, get_adapter
from ..providers.base import ASPECT_RATIOS, IMAGE_RESOLUTIONS

FEATURE_LABELS = {
    "reference": "参考图",
    "img2img": "图生图",
    "first_frame": "首帧",
    "last_frame": "尾帧",
    "seed": "随机种子",
    "negative": "反向提示词",
    "batch": "批量",
    "inpaint": "局部重绘",
}

CHANNEL_FIELDS = """
  m.*,
  c.name AS channel_name,
  c.protocol AS protocol,
  c.base_url AS base_url,
  c.headers AS headers,
  c.enabled AS channel_enabled
"""


@dataclass
class Target:
    model_id: str
    model_name: str
    modality: str
    channel_id: str
    channel_name: str
    protocol: str
    base_url: str
    headers: dict[str, str]
    upstream_model: str
    overrides: dict[str, Any]
    adapter: Any
    price: dict[str, Any]

    def public(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_name": self.model_name,
            "modality": self.modality,
            "channel_id": self.channel_id,
            "channel_name": self.channel_name,
            "protocol": self.protocol,
            "upstream_model": self.upstream_model,
        }


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def load_model(conn: sqlite3.Connection, model_id: str) -> dict[str, Any]:
    row = db.one(
        conn,
        f"SELECT {CHANNEL_FIELDS} FROM models m LEFT JOIN channels c ON c.id = m.channel_id "
        "WHERE m.id = ?",
        (model_id,),
    )
    if not row:
        raise Unsupported("模型不存在")
    row["caps"] = db.loads(row["caps"], {})
    row["params"] = db.loads(row["params"], {})
    row["params"].pop("size", None)
    if row.get("modality") == "image":
        row["params"].pop("aspect_ratio", None)
        row["params"].pop("resolution", None)
    row["price"] = db.loads(row["price"], {})
    row["overrides"] = db.loads(row["overrides"], {})
    row["headers"] = db.loads(row["headers"], {})
    try:
        row["adapter"] = get_adapter(row["protocol"]) if row.get("protocol") else None
    except KeyError:
        row["adapter"] = None
    available, reason = availability(conn, row)
    row["available"] = available
    row["reason"] = reason
    return row


def needs_key(model: dict[str, Any]) -> bool:
    return model.get("protocol") != "mock"


def availability(conn: sqlite3.Connection, model: dict[str, Any]) -> tuple[bool, str]:
    if not model.get("enabled"):
        return False, "模型已停用"
    if not model.get("channel_id") or not model.get("channel_name"):
        return False, "未绑定服务渠道"
    if not model.get("channel_enabled"):
        return False, "渠道已停用"
    adapter = model.get("adapter")
    if not adapter:
        return False, "未知协议"
    if model["modality"] not in adapter.modalities:
        return False, "协议不支持该类型"
    if model.get("protocol") != "mock" and not model.get("base_url"):
        return False, "缺少服务地址"
    if needs_key(model):
        count = db.scalar(
            conn,
            "SELECT COUNT(*) FROM channel_keys WHERE channel_id = ? AND enabled = 1",
            (model["channel_id"],),
        )
        if not count:
            return False, "没有可用密钥"
        if not pick_key(conn, model["channel_id"]):
            return False, "密钥全部冷却中"
    return True, ""


def check(conn: sqlite3.Connection, model: dict[str, Any], req: GenRequest) -> None:
    ok, reason = availability(conn, model)
    if not ok:
        raise Unsupported(reason)
    if model["modality"] == "video" and req.count != 1:
        raise Unsupported("视频任务每次只能生成一个")
    caps = model.get("caps", {})
    if req.refs:
        max_refs = int(caps.get("max_refs", 0))
        if max_refs <= 0:
            raise Unsupported("当前模型不支持参考图")
        if len(req.refs) > max_refs:
            raise Unsupported(f"当前模型最多接受 {max_refs} 张参考图")
    max_count = int(caps.get("max_count", 1))
    if req.count > max_count:
        raise Unsupported(f"当前模型单次最多生成 {max_count} 张")
    if req.negative and "negative" not in caps.get("features", []):
        raise Unsupported("当前模型不支持反向提示词")
    if req.params.get("seed") not in (None, "") and "seed" not in caps.get("features", []):
        raise Unsupported("当前模型不支持随机种子")
    if model["modality"] == "image":
        aspect = str(req.params.get("aspect_ratio") or "1:1")
        resolution = str(req.params.get("resolution") or "1K").upper()
        if aspect not in ASPECT_RATIOS:
            raise Unsupported(f"不支持的画幅比例：{aspect}")
        if resolution not in IMAGE_RESOLUTIONS:
            raise Unsupported(f"不支持的清晰度：{resolution}")
    for key, value in req.params.items():
        if key.startswith("_"):
            continue
        options = model.get("params", {}).get(key)
        if options and str(value) not in {str(option) for option in options}:
            raise Unsupported(f"参数 {key} 不支持取值 {value}")
    model["adapter"].validate(req)


def target(model: dict[str, Any]) -> Target:
    return Target(
        model_id=model["id"],
        model_name=model["name"],
        modality=model["modality"],
        channel_id=model["channel_id"],
        channel_name=model["channel_name"],
        protocol=model["protocol"],
        base_url=model["base_url"],
        headers=model.get("headers") or {},
        upstream_model=model["upstream_model"],
        overrides=model.get("overrides") or {},
        adapter=model["adapter"],
        price=model.get("price") or {},
    )


def quote_price(price: dict[str, Any], req: GenRequest) -> float | None:
    mode = price.get("mode", "unconfigured")
    amount = float(price.get("amount") or 0)
    if mode == "unconfigured" or amount <= 0:
        return None
    quantity = 1
    if mode == "per_image":
        quantity = req.count
    elif mode == "per_second":
        try:
            quantity = req.count * float(req.params.get("duration") or 0)
        except (TypeError, ValueError):
            quantity = 0
        if quantity <= 0:
            return None
    return round(amount * quantity, 4)


def estimate(model: dict[str, Any], req: GenRequest) -> dict[str, Any]:
    price = model.get("price") or {}
    amount = quote_price(price, req)
    return {
        "known": amount is not None,
        "amount": amount or 0,
        "min": amount or 0,
        "max": amount or 0,
        "currency": price.get("currency", "CNY"),
        "channel": model.get("channel_name", ""),
    }


def pick_key(conn: sqlite3.Connection, channel_id: str) -> dict[str, Any] | None:
    stamp = now_iso()
    return db.one(
        conn,
        """
        SELECT * FROM channel_keys
        WHERE channel_id = ? AND enabled = 1
          AND (cooldown_until IS NULL OR cooldown_until <= ?)
        ORDER BY fail_count ASC, COALESCE(last_used_at, '0000') ASC, ok_count DESC
        LIMIT 1
        """,
        (channel_id, stamp),
    )


def available_keys(conn: sqlite3.Connection, channel_id: str) -> list[dict[str, Any]]:
    stamp = now_iso()
    return db.rows(
        conn,
        """
        SELECT * FROM channel_keys
        WHERE channel_id = ? AND enabled = 1
          AND (cooldown_until IS NULL OR cooldown_until <= ?)
        ORDER BY fail_count ASC, COALESCE(last_used_at, '0000') ASC, ok_count DESC
        """,
        (channel_id, stamp),
    )


def channel_needs_key(conn: sqlite3.Connection, channel_id: str) -> bool:
    row = db.one(conn, "SELECT protocol FROM channels WHERE id = ?", (channel_id,))
    if not row or row["protocol"] == "mock":
        return False
    count = db.scalar(
        conn, "SELECT COUNT(*) FROM channel_keys WHERE channel_id = ? AND enabled = 1", (channel_id,)
    )
    return int(count or 0) == 0


def cooldown_seconds(kind: str) -> int:
    return {"auth": 900, "quota": 120}.get(kind, 0)


def record_key_success(conn: sqlite3.Connection, key_id: str | None) -> None:
    if not key_id:
        return
    conn.execute(
        "UPDATE channel_keys SET status='ok', ok_count=ok_count+1, fail_count=0, "
        "last_used_at=?, last_error=NULL, cooldown_until=NULL WHERE id=?",
        (now_iso(), key_id),
    )


def record_key_failure(conn: sqlite3.Connection, key_id: str | None, error: ProviderError) -> None:
    if not key_id:
        return
    seconds = cooldown_seconds(error.kind)
    until = (
        (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat(timespec="seconds")
        if seconds
        else None
    )
    conn.execute(
        "UPDATE channel_keys SET status='error', fail_count=fail_count+1, last_used_at=?, "
        "last_error=?, cooldown_until=? WHERE id=?",
        (now_iso(), error.message[:400], until, key_id),
    )


def build_request(
    *,
    upstream_model: str,
    prompt: str,
    negative: str,
    refs: list[RefImage],
    count: int,
    params: dict[str, Any],
) -> GenRequest:
    return GenRequest(
        model=upstream_model,
        prompt=prompt,
        negative=negative,
        refs=refs,
        count=max(1, count),
        params={key: value for key, value in params.items() if value not in (None, "")},
    )
