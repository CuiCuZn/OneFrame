from __future__ import annotations

import base64
import io

import httpx
import pytest
from PIL import Image

from app.errors import ProviderError
from app.providers.base import GenRequest, ProviderContext, RefImage, image_size
from app.providers.gemini import GeminiImageAdapter
from app.providers.mock import MockAdapter
from app.providers.openai_images import OpenAIImagesAdapter
from app.providers.openai_video import OpenAIVideoAdapter


def png_bytes(size=(64, 64), color=(180, 90, 40)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def context(adapter, request, handler, base_url="https://relay.example.com/v1"):
    seen: list[httpx.Request] = []

    def wrap(request_: httpx.Request) -> httpx.Response:
        seen.append(request_)
        return handler(request_)

    client = httpx.AsyncClient(transport=httpx.MockTransport(wrap))
    ctx = ProviderContext(
        client=client,
        base_url=base_url,
        api_key="sk-test",
        headers={},
        request=request,
        modality="image",
    )
    return ctx, seen, client


@pytest.mark.asyncio
async def test_openai_images_generations_b64():
    adapter = OpenAIImagesAdapter()
    payload = {"data": [{"b64_json": base64.b64encode(png_bytes()).decode()}]}
    request = GenRequest(model="gpt-image-1", prompt="a cat", count=2, params={"size": "1024x1024"})
    ctx, seen, client = context(adapter, request, lambda _req: httpx.Response(200, json=payload))
    result = await adapter.submit(ctx)
    await client.aclose()

    assert len(result.outputs) == 1
    assert result.outputs[0].data and result.outputs[0].data[:4] == b"\x89PNG"
    body = seen[0].read().decode()
    assert '"model":"gpt-image-1"' in body.replace(" ", "")
    assert '"n":2' in body.replace(" ", "")
    assert '"size":"1024x1024"' in body.replace(" ", "")
    assert '"response_format":"url"' in body.replace(" ", "")
    assert seen[0].headers["authorization"] == "Bearer sk-test"
    assert str(seen[0].url).endswith("/images/generations")


@pytest.mark.asyncio
async def test_openai_images_resolves_relative_url():
    adapter = OpenAIImagesAdapter()
    payload = {"data": [{"url": "/v1/media/out.webp"}]}
    request = GenRequest(model="muse-image", prompt="portrait")
    ctx, seen, client = context(
        adapter,
        request,
        lambda _req: httpx.Response(200, json=payload),
        base_url="http://127.0.0.1:18610/v1",
    )

    downloaded_urls = []
    async def fake_fetch(ctx_, url):
        downloaded_urls.append(url)
        return png_bytes(color=(1, 2, 3))

    adapter.fetch_bytes = fake_fetch  # type: ignore[assignment]
    result = await adapter.submit(ctx)
    await client.aclose()

    assert len(result.outputs) == 1
    assert downloaded_urls == ["http://127.0.0.1:18610/v1/media/out.webp"]
    assert result.outputs[0].data and result.outputs[0].data[:4] == b"\x89PNG"


@pytest.mark.asyncio
async def test_openai_images_edits_uses_multipart():
    adapter = OpenAIImagesAdapter()
    payload = {"data": [{"url": "https://cdn.example.com/out.png"}]}
    reference = RefImage(name="pose", mime="image/png", data=png_bytes())

    def handler(_request):
        return httpx.Response(200, json=payload)

    request = GenRequest(model="gpt-image-1", prompt="same pose", refs=[reference])
    ctx, seen, client = context(adapter, request, handler)

    async def fake_fetch(ctx_, url):
        return png_bytes(color=(10, 20, 30))

    adapter.fetch_bytes = fake_fetch  # type: ignore[assignment]
    result = await adapter.submit(ctx)
    await client.aclose()

    assert str(seen[0].url).endswith("/images/edits")
    assert seen[0].headers["content-type"].startswith("multipart/form-data")
    payload_bytes = seen[0].read()
    assert b'name="image"' in payload_bytes
    assert b'name="response_format"' in payload_bytes
    assert b"url" in payload_bytes
    assert result.outputs[0].data is not None


@pytest.mark.asyncio
async def test_openai_images_auth_error_is_classified():
    adapter = OpenAIImagesAdapter()
    request = GenRequest(model="gpt-image-1", prompt="x")
    ctx, _seen, client = context(
        adapter, request, lambda _req: httpx.Response(401, json={"error": {"message": "bad key"}})
    )
    with pytest.raises(ProviderError) as info:
        await adapter.submit(ctx)
    await client.aclose()
    assert info.value.kind == "auth"


@pytest.mark.asyncio
async def test_gemini_image_inline_data():
    adapter = GeminiImageAdapter()
    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "done"},
                        {
                            "inlineData": {
                                "mimeType": "image/png",
                                "data": base64.b64encode(png_bytes()).decode(),
                            }
                        },
                    ]
                }
            }
        ]
    }
    request = GenRequest(model="gemini-2.5-flash-image", prompt="a fox", refs=[RefImage(data=png_bytes())])
    ctx, seen, client = context(
        adapter,
        request,
        lambda _req: httpx.Response(200, json=payload),
        base_url="https://generativelanguage.googleapis.com/v1beta",
    )
    result = await adapter.submit(ctx)
    await client.aclose()
    assert result.outputs and result.outputs[0].mime == "image/png"
    assert str(seen[0].url).endswith("/models/gemini-2.5-flash-image:generateContent")
    assert seen[0].headers["x-goog-api-key"] == "sk-test"


@pytest.mark.asyncio
async def test_openai_video_polls_until_content():
    adapter = OpenAIVideoAdapter()
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.method == "POST":
            return httpx.Response(200, json={"id": "vid_1", "status": "queued"})
        if request.url.path.endswith("/content"):
            return httpx.Response(200, content=b"\x00\x00\x00\x18ftypmp42", headers={"content-type": "video/mp4"})
        return httpx.Response(200, json={"id": "vid_1", "status": "completed", "progress": 100})

    request = GenRequest(model="sora-2", prompt="rain", params={"seconds": "4"})
    ctx, _seen, client = context(adapter, request, handler, base_url="https://api.openai.com/v1")
    ctx.modality = "video"
    submitted = await adapter.submit(ctx)
    assert submitted.upstream_id == "vid_1"
    polled = await adapter.poll(ctx, submitted)
    await client.aclose()
    assert polled.done and polled.outputs[0].kind == "video"
    assert any(path.endswith("/content") for path in calls)


@pytest.mark.asyncio
async def test_mock_adapter_returns_pngs():
    adapter = MockAdapter()
    request = GenRequest(model="mock-image", prompt="示例", count=3)
    ctx, _seen, client = context(adapter, request, lambda _req: httpx.Response(500))
    result = await adapter.submit(ctx)
    await client.aclose()
    assert len(result.outputs) == 3
    for output in result.outputs:
        with Image.open(io.BytesIO(output.data)) as image:
            assert image.size == (1024, 1024)


def test_image_size_from_aspect_and_resolution():
    assert image_size("1:1", "1K") == "1024x1024"
    assert image_size("4:3", "2K") == "2048x1536"
    assert image_size("9:16", "1K") == "576x1024"
    assert image_size("16:9", "4K") == "4096x2304"
    assert image_size("unknown", "nope") == "1024x1024"


@pytest.mark.asyncio
async def test_openai_images_derives_size_from_aspect_and_resolution():
    adapter = OpenAIImagesAdapter()
    payload = {"data": [{"b64_json": base64.b64encode(png_bytes()).decode()}]}
    request = GenRequest(
        model="gpt-image-1",
        prompt="portrait",
        params={"aspect_ratio": "9:16", "resolution": "1K"},
    )
    ctx, seen, client = context(adapter, request, lambda _req: httpx.Response(200, json=payload))
    await adapter.submit(ctx)
    await client.aclose()
    body = seen[0].read().decode().replace(" ", "")
    assert '"size":"576x1024"' in body


@pytest.mark.asyncio
async def test_openai_images_response_format_override():
    adapter = OpenAIImagesAdapter()
    payload = {"data": [{"b64_json": base64.b64encode(png_bytes()).decode()}]}
    request = GenRequest(model="gpt-image-1", prompt="x")
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=payload)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ctx = ProviderContext(
        client=client,
        base_url="https://relay.example.com/v1",
        api_key="sk-test",
        headers={},
        request=request,
        overrides={"response_format": "b64_json"},
        modality="image",
    )
    await adapter.submit(ctx)
    await client.aclose()
    assert '"response_format":"b64_json"' in seen[0].read().decode().replace(" ", "")


@pytest.mark.asyncio
async def test_openai_video_prefers_result_url():
    adapter = OpenAIVideoAdapter()
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.method == "POST":
            return httpx.Response(200, json={"id": "task_1", "status": "queued"})
        if request.url.path.endswith("/content"):
            return httpx.Response(404, json={"detail": "Not Found"})
        if request.url.path.endswith("/v1/media/x.mp4"):
            return httpx.Response(200, content=b"fake-mp4", headers={"content-type": "video/mp4"})
        return httpx.Response(
            200,
            json={
                "id": "task_1",
                "status": "completed",
                "result": {"url": "/v1/media/x.mp4", "kind": "video"},
            },
        )

    request = GenRequest(model="muse-video", prompt="rain")
    ctx, _seen, client = context(adapter, request, handler, base_url="http://127.0.0.1:18610/v1")
    ctx.modality = "video"
    submitted = await adapter.submit(ctx)
    assert submitted.upstream_id == "task_1"
    polled = await adapter.poll(ctx, submitted)
    await client.aclose()
    assert polled.done and polled.outputs[0].data == b"fake-mp4"
    assert polled.external_url == "http://127.0.0.1:18610/v1/media/x.mp4"
    assert not any(path.endswith("/content") for path in calls)
