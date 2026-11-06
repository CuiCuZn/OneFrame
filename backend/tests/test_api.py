from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app import db
from app.main import app


def wait_for_job(job_id: str, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with db.connect() as conn:
            row = db.one(conn, "SELECT * FROM jobs WHERE id = ?", (job_id,))
        if row and row["status"] in ("succeeded", "failed", "canceled", "uncertain"):
            return row
        time.sleep(0.3)
    raise AssertionError("job did not finish")


def test_health_and_catalog():
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200 and health.json()["ok"]
        catalog = client.get("/api/catalog").json()
        assert catalog["styles"] and catalog["protocols"]


def test_generate_with_demo_model_end_to_end():
    with TestClient(app) as client:
        models = client.get("/api/models").json()
        demo = next(model for model in models if model["modality"] == "image")
        response = client.post(
            "/api/generate",
            json={
                "model_id": demo["id"],
                "prompt": "测试提示词",
                "count": 2,
                "params": {"size": "1024x1024"},
                "refs": [],
            },
        )
        assert response.status_code == 200, response.text
        job_id = response.json()["job_id"]
        row = wait_for_job(job_id)
        assert row["status"] == "succeeded", row["error"]
        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["asset_count"] == 2
        asset = detail["assets"][0]
        assert asset["prompt"] == "测试提示词"
        media = client.get(asset["url"])
        assert media.status_code == 200
        assert media.headers["content-type"].startswith("image/")
        thumb = client.get(asset["thumb_url"])
        assert thumb.status_code == 200


def test_prompt_compile_endpoint():
    with TestClient(app) as client:
        result = client.post(
            "/api/prompt/compile",
            json={
                "refs": [{"role": "pose", "title": "P001"}, {"role": "character", "title": "短发"}],
                "style": "anime",
                "extra": "教室",
                "language": "zh",
            },
        ).json()
        assert "图1 = 人物外貌" in result["prompt"]
        assert "教室" in result["prompt"]


def test_invalid_generate_is_422():
    with TestClient(app) as client:
        models = client.get("/api/models").json()
        demo = next(model for model in models if model["modality"] == "image")
        response = client.post(
            "/api/generate",
            json={"model_id": demo["id"], "prompt": "", "count": 1, "refs": []},
        )
        assert response.status_code == 422
