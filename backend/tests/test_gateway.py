from __future__ import annotations

import base64
import io
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import db
from app.errors import ProviderError
from app.main import app
from app.providers.base import GenRequest, Output, ProviderContext, SubmitResult
from app.providers.generic import GenericAdapter
from app.providers.openai_images import OpenAIImagesAdapter


def png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (24, 24), (10, 120, 200)).save(buffer, "PNG")
    return buffer.getvalue()


def ctx_for(adapter, overrides, request, handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return ProviderContext(
        client=client,
        base_url="https://custom.example",
        api_key="token",
        headers={},
        request=request,
        overrides=overrides,
        modality="image",
    ), client


@pytest.mark.asyncio
async def test_generic_adapter_sync_template():
    adapter = GenericAdapter()
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, json={"result": {"images": [{"b64": base64.b64encode(png()).decode()}]}}
        )

    config = {
        "path": "/v2/draw",
        "body": {"model": "{{model}}", "prompt": "{{prompt}}", "n": "{{count}}"},
        "response": {"items": "result.images", "b64": "b64"},
    }
    request = GenRequest(model="draw-v2", prompt="一只狐狸", count=2)
    ctx, client = ctx_for(adapter, {"generic": config}, request, handler)
    result = await adapter.submit(ctx)
    await client.aclose()

    assert result.outputs and result.outputs[0].data[:4] == b"\x89PNG"
    body = seen[0].read().decode()
    assert '"n":2' in body.replace(" ", "")
    assert "draw-v2" in body
    assert str(seen[0].url) == "https://custom.example/v2/draw"
    assert seen[0].headers["authorization"] == "Bearer token"


@pytest.mark.asyncio
async def test_generic_adapter_async_polling():
    adapter = GenericAdapter()
    adapter.fetch_bytes = _fake_fetch  # type: ignore[assignment]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"data": {"task_id": "task-9"}})
        assert request.url.path == "/tasks/task-9"
        return httpx.Response(
            200,
            json={
                "data": {
                    "task_status": "succeed",
                    "progress": 100,
                    "task_result": {"videos": [{"url": "https://cdn.example/out.mp4"}]},
                }
            },
        )

    config = {
        "path": "/videos",
        "body": {"prompt": "{{prompt}}", "model": "{{model}}"},
        "response": {"id": "data.task_id"},
        "poll": {
            "path": "/tasks/{{id}}",
            "status": "data.task_status",
            "success": ["succeed"],
            "failure": ["failed"],
            "items": "data.task_result.videos",
            "url": "url",
        },
    }
    request = GenRequest(model="v1", prompt="镜头推进")
    ctx, client = ctx_for(adapter, {"generic": config}, request, handler)
    ctx.modality = "video"
    submitted = await adapter.submit(ctx)
    assert submitted.upstream_id == "task-9"
    polled = await adapter.poll(ctx, submitted)
    await client.aclose()
    assert polled.done and polled.outputs[0].kind == "video"
    assert polled.outputs[0].data == b"fake-video"


async def _fake_fetch(_ctx, url):
    assert url.endswith("out.mp4")
    return b"fake-video"


def _create_channel(client: TestClient, name: str, protocol: str, key_count: int = 1) -> str:
    keys = [] if protocol == "mock" else [
        {"label": f"k{index + 1}", "secret": f"sk-{index + 1}"} for index in range(key_count)
    ]
    response = client.post(
        "/api/channels",
        json={
            "name": name,
            "protocol": protocol,
            "base_url": "" if protocol == "mock" else f"https://{name}.example/v1",
            "keys": keys,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _create_model(client: TestClient, name: str, channel_id: str, upstream: str) -> str:
    response = client.post(
        "/api/models",
        json={
            "name": name,
            "modality": "image",
            "channel_id": channel_id,
            "upstream_model": upstream,
            "description": "fixture",
            "enabled": True,
            "caps": {"max_refs": 1, "max_count": 2, "features": ["reference"], "sizes": [], "aspects": []},
            "params": {"size": ["1024x1024"]},
            "price": {"mode": "per_image", "amount": 0.01, "currency": "CNY"},
            "overrides": {},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _generate(client: TestClient, model_id: str) -> str:
    response = client.post(
        "/api/generate",
        json={"model_id": model_id, "prompt": "测试", "count": 1, "params": {"size": "1024x1024"}, "refs": []},
    )
    assert response.status_code == 200, response.text
    return response.json()["job_id"]


def _wait(job_id: str, timeout: float = 25.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with db.connect() as conn:
            row = db.one(conn, "SELECT * FROM jobs WHERE id = ?", (job_id,))
        if row and row["status"] in ("succeeded", "failed", "canceled", "uncertain"):
            return row
        time.sleep(0.25)
    raise AssertionError("job did not finish")


def test_failure_does_not_fall_back_to_another_vendor(monkeypatch):
    calls = {"count": 0}

    async def reject(self, ctx):
        calls["count"] += 1
        raise ProviderError("密钥失效", kind="auth")

    monkeypatch.setattr(OpenAIImagesAdapter, "submit", reject)

    with TestClient(app) as client:
        vendor_a = _create_channel(client, "vendor-a", "openai_image")
        vendor_c = _create_channel(client, "vendor-c", "mock")
        model_a = _create_model(client, "a · A厂", vendor_a, "a-model")
        _create_model(client, "a · C厂", vendor_c, "mock-image")

        job_id = _generate(client, model_a)
        row = _wait(job_id)
        assert row["status"] == "failed"
        assert calls["count"] == 1
        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["asset_count"] == 0
        channels = {item.get("channel") for item in detail["attempts"] if item.get("channel")}
        assert channels == {"vendor-a"}


def test_ambiguous_submission_is_uncertain_and_not_retried(monkeypatch):
    calls = {"count": 0}

    async def timeout(self, ctx):
        calls["count"] += 1
        raise ProviderError("读取超时，可能已提交", kind="network", ambiguous=True, retryable=False)

    monkeypatch.setattr(OpenAIImagesAdapter, "submit", timeout)

    with TestClient(app) as client:
        vendor = _create_channel(client, "vendor-timeout", "openai_image", key_count=2)
        model_id = _create_model(client, "timeout model", vendor, "gpt-image-1")
        job_id = _generate(client, model_id)
        row = _wait(job_id)
        assert row["status"] == "uncertain"
        assert calls["count"] == 1
        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["asset_count"] == 0


def test_auth_failure_fails_without_retry(monkeypatch):
    calls = {"count": 0}

    async def reject(self, ctx):
        calls["count"] += 1
        raise ProviderError("key 无效", kind="auth")

    monkeypatch.setattr(OpenAIImagesAdapter, "submit", reject)

    with TestClient(app) as client:
        vendor = _create_channel(client, "vendor-keys", "openai_image", key_count=2)
        model_id = _create_model(client, "key pool model", vendor, "gpt-image-1")
        job_id = _generate(client, model_id)
        row = _wait(job_id)
        assert row["status"] == "failed"
        assert calls["count"] == 1
        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["asset_count"] == 0

        channel = next(item for item in client.get("/api/channels").json() if item["id"] == vendor)
        statuses = sorted(key["status"] for key in channel["keys"])
        assert statuses == ["error", "untested"]
        bad = next(key for key in channel["keys"] if key["status"] == "error")
        assert bad["cooldown_until"]
        good = next(key for key in channel["keys"] if key["status"] == "untested")
        assert good["ok_count"] == 0


def test_upstream_error_does_not_try_second_key(monkeypatch):
    calls = {"count": 0}

    async def upstream_down(self, ctx):
        calls["count"] += 1
        raise ProviderError("上游 500", kind="upstream", status=500)

    monkeypatch.setattr(OpenAIImagesAdapter, "submit", upstream_down)

    with TestClient(app) as client:
        vendor = _create_channel(client, "vendor-500", "openai_image", key_count=2)
        model_id = _create_model(client, "upstream fail", vendor, "gpt-image-1")
        job_id = _generate(client, model_id)
        row = _wait(job_id)
        assert row["status"] == "failed"
        assert calls["count"] == 1
