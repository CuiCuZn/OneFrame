from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import config, db
from app.core import storage, tools
from app.errors import Unsupported
from app.main import app


@pytest.fixture(autouse=True)
def clean_assets():
    db.init_db()
    with db.connect() as conn:
        conn.execute("DELETE FROM library_items")
        conn.execute("DELETE FROM library_facets")
        conn.execute("DELETE FROM assets")
        conn.execute("DELETE FROM jobs")
        conn.execute("DELETE FROM prompts WHERE builtin = 0")
    yield


def _image_bytes(color=(40, 80, 120)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (90, 120), color).save(buffer, "PNG")
    return buffer.getvalue()


def _make_asset(name: str, color=(40, 80, 120)) -> dict:
    record = storage.save_output(_image_bytes(color), "image")
    asset_id = db.new_id()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO assets (id, kind, path, thumb_path, width, height, bytes, prompt,"
            " model_name, origin, meta, root_id, version, created_at) VALUES"
            " (?, 'image', ?, ?, ?, ?, ?, 'test', 'demo', 'generated', '{}', ?, 1, ?)",
            (
                asset_id,
                record["path"],
                record.get("thumb_path"),
                record.get("width"),
                record.get("height"),
                record.get("bytes"),
                asset_id,
                db.now(),
            ),
        )
        return db.one(conn, "SELECT * FROM assets WHERE id = ?", (asset_id,))


def test_asset_refs_and_zip():
    library_path = config.DATA_DIR / storage.save_upload("ref.png", _image_bytes((10, 20, 30)))["path"]
    with db.connect() as conn:
        library_id = db.new_id()
        conn.execute(
            "INSERT INTO library_items (id, source, external_id, kind, title, subtitle, category,"
            " image_path, group_key, created_at) VALUES (?, 'folder:x', 'ref', 'pose', '参考', '',"
            " '站姿', ?, 'g1', ?)",
            (library_id, str(library_path), db.now()),
        )
    asset = _make_asset("main")
    with db.connect() as conn:
        conn.execute(
            "UPDATE assets SET meta = ? WHERE id = ?",
            (
                db.dumps(
                    {
                        "refs_snapshot": [
                            {"source": "library", "id": library_id, "role": "pose", "name": "参考"},
                            {"source": "asset", "id": asset["id"], "role": "reference", "name": "源图"},
                        ]
                    }
                ),
                asset["id"],
            ),
        )

    with TestClient(app) as client:
        refs = client.get(f"/api/assets/{asset['id']}/refs")
        assert refs.status_code == 200
        items = refs.json()["items"]
        assert len(items) == 2
        assert items[0]["url"].startswith("/api/library/")
        assert items[1]["thumb_url"].endswith("size=thumb")

        bundle = client.get(f"/api/assets/{asset['id']}/references.zip")
        assert bundle.status_code == 200
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
            names = archive.namelist()
            assert len(names) == 2
            assert any(name.endswith(".png") for name in names)
            assert "missing.txt" not in names


def test_asset_refs_zip_reports_missing_file():
    asset = _make_asset("main")
    with db.connect() as conn:
        conn.execute(
            "UPDATE assets SET meta = ? WHERE id = ?",
            (
                db.dumps({"refs_snapshot": [{"source": "asset", "id": "missing", "role": "reference"}]}),
                asset["id"],
            ),
        )
    with TestClient(app) as client:
        bundle = client.get(f"/api/assets/{asset['id']}/references.zip")
        assert bundle.status_code == 200
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
            assert "missing.txt" in archive.namelist()


def test_import_url_rejects_private_address():
    with TestClient(app) as client:
        response = client.post("/api/assets/import-url", json={"url": "http://127.0.0.1:9/a.png"})
        assert response.status_code == 409
        response = client.post("/api/assets/import-url", json={"url": "file:///etc/passwd"})
        assert response.status_code == 409


def test_tool_prompts_and_validation():
    prompt = tools.build_prompt("extract_costume", {}, "只保留连衣裙和鞋")
    assert "Extract the complete outfit" in prompt
    assert "只保留连衣裙和鞋" in prompt
    view = tools.build_prompt("character", {"mode": "view", "preset": "profile_left"})
    assert "left profile" in view
    with pytest.raises(Unsupported):
        tools.build_prompt("character", {"mode": "view", "preset": "nope"})
    with pytest.raises(Unsupported):
        tools.build_prompt("inpaint", {}, "")

    model = {
        "modality": "image",
        "caps": {"max_refs": 2, "features": ["reference"]},
    }

    class FakeAdapter:
        supports_reference = True
        supports_mask = False

    tools.validate_tool("extract_costume", {"source_asset_id": "a"}, model, FakeAdapter(), 1)
    with pytest.raises(Unsupported):
        tools.validate_tool("inpaint", {"source_asset_id": "a"}, model, FakeAdapter(), 1)


def test_generate_tool_uses_server_prompt_and_source():
    source = _make_asset("source")
    with TestClient(app) as client:
        models = client.get("/api/models").json()
        demo = next(model for model in models if model["modality"] == "image" and model["available"])
        response = client.post(
            "/api/generate",
            json={
                "model_id": demo["id"],
                "prompt": "只保留裙子",
                "negative": "",
                "count": 1,
                "params": {},
                "refs": [],
                "tool": "extract_costume",
                "options": {"source_asset_id": source["id"]},
            },
        )
        assert response.status_code == 200, response.text
        job_id = response.json()["job_id"]
        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["request"]["tool"] == "extract_costume"
        assert "Extract the complete outfit" in detail["request"]["prompt"]
        assert detail["request"]["refs"][0]["asset_id"] == source["id"]


def test_split_upscale_and_versions():
    source = _make_asset("source")
    with TestClient(app) as client:
        split = client.post(
            f"/api/assets/{source['id']}/split",
            json={"rows": 2, "columns": 2, "cells": [0, 1]},
        )
        assert split.status_code == 200, split.text
        items = split.json()["items"]
        assert len(items) == 2
        assert all(item["origin"] == "split" for item in items)
        assert all(item["parent_id"] == source["id"] for item in items)
        assert all(item["version"] == 1 for item in items)

        upscale = client.post(f"/api/assets/{source['id']}/upscale", json={"factor": 2})
        assert upscale.status_code == 200, upscale.text
        bigger = upscale.json()
        assert bigger["width"] == source["width"] * 2
        assert bigger["height"] == source["height"] * 2
        assert bigger["root_id"] == source["id"]
        assert bigger["version"] == 2

        versions = client.get(f"/api/assets/{bigger['id']}/versions").json()
        assert [item["id"] for item in versions["items"]] == [source["id"], bigger["id"]]

        split_versions = client.get(f"/api/assets/{items[0]['id']}/versions").json()
        assert [item["id"] for item in split_versions["items"]] == [items[0]["id"]]


def test_prompt_library_and_enhance():
    with TestClient(app) as client:
        builtins = client.get("/api/prompts", params={"category": "quality"}).json()
        assert builtins["total"] >= 1
        builtin_id = builtins["items"][0]["id"]
        assert client.delete(f"/api/prompts/{builtin_id}").status_code == 409

        created = client.post(
            "/api/prompts",
            json={
                "title": "我的光影",
                "category": "lighting",
                "text": "柔和的窗边侧光",
                "negative": "",
                "tags": "光",
            },
        )
        assert created.status_code == 200, created.text
        prompt_id = created.json()["id"]
        favorited = client.post(f"/api/prompts/{prompt_id}/favorite").json()
        assert favorited["favorite"] is True
        updated = client.put(
            f"/api/prompts/{prompt_id}",
            json={
                "title": "我的光影 v2",
                "category": "lighting",
                "text": "柔和的窗边侧光，暖色阴影",
                "negative": "",
                "tags": "光",
            },
        )
        assert updated.json()["title"] == "我的光影 v2"
        assert client.delete(f"/api/prompts/{prompt_id}").status_code == 200

        enhanced = client.post(
            "/api/prompt/enhance",
            json={
                "prompt": "女孩在咖啡馆",
                "style": "cinematic",
                "modality": "image",
                "has_refs": True,
            },
        )
        assert enhanced.status_code == 200, enhanced.text
        payload = enhanced.json()
        assert "女孩在咖啡馆" in payload["prompt"]
        assert payload["negative"]
        assert payload["notes"]
