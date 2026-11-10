from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from app.core import prompt_rewrite
from app.main import app


def _payload(mode: str) -> dict:
    return {
        "prompt": "女孩在咖啡馆",
        "negative": "",
        "style": "cinematic",
        "modality": "image",
        "has_refs": False,
        "language": "zh",
        "mode": mode,
    }


def test_clean_completion_strips_reasoning_and_formatting():
    raw = "<think>hidden reasoning</think>\n```text\n提示词：\"电影感中景，女孩坐在窗边。\"\n```"
    assert prompt_rewrite.clean_completion(raw) == "电影感中景，女孩坐在窗边。"


def test_enhance_uses_llm_and_strips_think(monkeypatch):
    async def fake_chat(conn, system, user):
        assert "女孩在咖啡馆" in user
        return "<think>planning</think>\n电影感中景：女孩坐在咖啡馆窗边，柔和侧光。"

    monkeypatch.setattr(prompt_rewrite, "_chat", fake_chat)
    with TestClient(app) as client:
        response = client.post("/api/prompt/enhance", json=_payload("llm"))
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["source"] == "llm"
        assert result["model"] == prompt_rewrite.MODEL
        assert result["prompt"] == "电影感中景：女孩坐在咖啡馆窗边，柔和侧光。"
        assert "<think>" not in result["prompt"]
        assert result["negative"]


def test_enhance_falls_back_to_rules_when_model_fails(monkeypatch):
    async def fake_chat(conn, system, user):
        raise httpx.ConnectTimeout("upstream timeout")

    monkeypatch.setattr(prompt_rewrite, "_chat", fake_chat)
    with TestClient(app) as client:
        response = client.post("/api/prompt/enhance", json=_payload("llm"))
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["source"] == "rules"
        assert result["fallback_reason"] == "文本模型超时"
        assert "女孩在咖啡馆" in result["prompt"]
        assert any("回退本地规则" in note for note in result["notes"])


def test_rules_mode_stays_deterministic():
    with TestClient(app) as client:
        first = client.post("/api/prompt/enhance", json=_payload("rules")).json()
        second = client.post("/api/prompt/enhance", json=_payload("rules")).json()
        assert first["source"] == "rules"
        assert first["prompt"] == second["prompt"]
        assert "女孩在咖啡馆" in first["prompt"]
