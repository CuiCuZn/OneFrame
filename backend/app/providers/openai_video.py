"""OpenAI Videos compatible protocol (``/videos`` task + content download)."""

from __future__ import annotations

from urllib.parse import urlsplit

from ..errors import ProviderError, Unsupported
from .base import (
    Adapter,
    GenRequest,
    Output,
    PollResult,
    ProviderContext,
    SubmitResult,
    mime_for,
    parse_json,
    pick,
    raise_for_status,
)

VIDEO_SIZES = {"480p": (854, 480), "720p": (1280, 720), "1080p": (1920, 1080)}


def _absolute(base_url: str, url: str) -> str:
    if url.startswith(("http://", "https://")):
        return url
    parts = urlsplit(base_url)
    if url.startswith("/"):
        return f"{parts.scheme}://{parts.netloc}{url}"
    return f"{base_url.rstrip('/')}/{url.lstrip('/')}"


def _video_url(payload: dict) -> str:
    for path in (
        "result.url",
        "video.url",
        "output.url",
        "data.0.url",
        "outputs.0.url",
        "url",
        "video_url",
        "result.video_url",
    ):
        value = pick(payload, path)
        if isinstance(value, str) and value:
            return value
    return ""


def _video_size(params: dict) -> str | None:
    size = params.get("size")
    if size:
        return str(size)
    resolution = str(params.get("resolution") or "").lower()
    if resolution in VIDEO_SIZES:
        width, height = VIDEO_SIZES[resolution]
        if str(params.get("aspect_ratio")) in ("9:16", "3:4"):
            width, height = height, width
        return f"{width}x{height}"
    return None


DONE = {"completed", "succeeded", "success", "done"}
FAILED = {"failed", "error", "cancelled", "canceled", "expired"}
RUNNING = {"queued", "pending", "in_progress", "processing", "running", "submitted"}


class OpenAIVideoAdapter(Adapter):
    protocol = "openai_video"
    label = "OpenAI Videos 兼容"
    modalities = {"video"}
    supports_reference = True
    param_keys = ("size", "seconds", "duration", "resolution", "aspect_ratio", "seed")
    about = (
        "标准 /v1/videos 异步任务协议：提交后返回任务 id，轮询状态，完成后从 "
        "/v1/videos/{id}/content 下载。支持一张首帧参考图（multipart input_reference）。"
    )

    def validate(self, req: GenRequest) -> None:
        super().validate(req)
        if req.count != 1:
            raise Unsupported("视频任务每次只能生成一个")
        if len(req.refs) > 1:
            raise Unsupported("OpenAI Videos 协议一次只接受一张首帧参考图")

    async def submit(self, ctx: ProviderContext) -> SubmitResult:
        req = ctx.request
        headers = {**ctx.headers, "Authorization": f"Bearer {ctx.api_key}"}
        seconds = req.params.get("seconds") or req.params.get("duration")
        size = _video_size(req.params)
        base = {"model": req.model, "prompt": req.prompt}
        if seconds:
            base["seconds"] = str(seconds)
        if size:
            base["size"] = str(size)
        if req.negative:
            base["negative_prompt"] = req.negative

        if req.refs:
            ref = req.refs[0]
            if not ref.data:
                raise ProviderError("首帧参考图内容为空", kind="params", retryable=False)
            form = {k: v for k, v in base.items()}
            resp = await ctx.client.post(
                ctx.url("/videos"),
                headers=headers,
                data=form,
                files={"input_reference": ("reference.png", ref.data, ref.mime or "image/png")},
                timeout=ctx.timeout,
            )
        else:
            resp = await ctx.client.post(
                ctx.url("/videos"), headers=headers, json=base, timeout=ctx.timeout
            )
        raise_for_status(resp, "视频提交")
        payload = parse_json(resp, "解析视频任务")
        job_id = payload.get("id") or payload.get("task_id") or payload.get("video_id")
        status = str(payload.get("status", "queued")).lower()
        if status in DONE:
            output, external = await self._output_from_payload(ctx, payload, job_id)
            return SubmitResult(outputs=[output], raw=payload, external_url=external)
        if not job_id:
            raise ProviderError("视频服务没有返回任务编号", kind="upstream")
        return SubmitResult(upstream_id=str(job_id), poll_after=4.0, raw=payload)

    async def poll(self, ctx: ProviderContext, handle: SubmitResult) -> PollResult:
        headers = {**ctx.headers, "Authorization": f"Bearer {ctx.api_key}"}
        resp = await ctx.client.get(
            ctx.url(f"/videos/{handle.upstream_id}"), headers=headers, timeout=60
        )
        raise_for_status(resp, "查询视频任务")
        payload = parse_json(resp, "解析视频任务")
        status = str(payload.get("status", "")).lower()
        raw_progress = payload.get("progress")
        progress = float(raw_progress) / 100 if isinstance(raw_progress, (int, float)) else 0.0
        if status in FAILED:
            message = (
                payload.get("error", {}).get("message")
                if isinstance(payload.get("error"), dict)
                else payload.get("error")
            )
            return PollResult(failed=True, error=message or f"上游视频任务状态：{status}")
        if status in DONE:
            output, external = await self._output_from_payload(ctx, payload, handle.upstream_id)
            return PollResult(
                done=True, outputs=[output], progress=1.0, raw=payload, external_url=external
            )
        if status and status not in RUNNING:
            raise ProviderError(f"视频服务返回未知状态：{status}", kind="upstream", retryable=False)
        return PollResult(progress=max(0.05, progress), raw=payload)

    async def _output_from_payload(
        self, ctx: ProviderContext, payload: dict, video_id: str | None
    ) -> tuple[Output, str | None]:
        """Prefer an explicit result URL from the task; fall back to /content."""

        url = _video_url(payload)
        if url:
            absolute = _absolute(ctx.base_url, url)
            try:
                return await self._fetch_media(ctx, absolute), absolute
            except ProviderError:
                # Some relays return a URL that still needs the content endpoint.
                pass
        return await self._download(ctx, video_id), None

    async def _fetch_media(self, ctx: ProviderContext, url: str) -> Output:
        headers = {**ctx.headers}
        if ctx.api_key:
            headers["Authorization"] = f"Bearer {ctx.api_key}"
        resp = await ctx.client.get(url, headers=headers, timeout=ctx.timeout, follow_redirects=True)
        if resp.status_code >= 400:
            raise_for_status(resp, "下载视频")
        if not resp.content:
            raise ProviderError("视频结果为空", kind="upstream")
        return Output(data=resp.content, kind="video", mime="video/mp4")

    async def _download(self, ctx: ProviderContext, video_id: str | None) -> Output:
        if not video_id:
            raise ProviderError("视频任务缺少编号，无法下载结果", kind="upstream")
        headers = {**ctx.headers, "Authorization": f"Bearer {ctx.api_key}"}
        resp = await ctx.client.get(
            ctx.url(f"/videos/{video_id}/content"),
            headers=headers,
            timeout=ctx.timeout,
            follow_redirects=True,
        )
        if resp.status_code >= 400:
            raise_for_status(resp, "下载视频")
        data = resp.content
        if not data:
            raise ProviderError("视频结果为空", kind="upstream")
        return Output(data=data, kind="video", mime=mime_for("video"))
