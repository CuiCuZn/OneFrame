"""Google Gemini / Imagen / Veo adapters (native Generative Language API)."""

from __future__ import annotations

import base64
import binascii
from typing import Any

from ..errors import ProviderError, Unsupported
from .base import (
    Adapter,
    GenRequest,
    Output,
    PollResult,
    ProviderContext,
    SubmitResult,
    b64_bytes,
    data_url,
    mime_for,
    parse_json,
    pick,
    raise_for_status,
)


def _model_path(model: str) -> str:
    return model[7:] if model.startswith("models/") else model


def _parts_payload(payload: dict) -> list[dict]:
    candidates = payload.get("candidates") or []
    if not candidates:
        return []
    parts = pick(candidates, "0.content.parts") or []
    return [part for part in parts if isinstance(part, dict)]


class GeminiImageAdapter(Adapter):
    protocol = "gemini_image"
    label = "Google Gemini / Imagen"
    modalities = {"image"}
    supports_reference = True
    param_keys = ("aspect_ratio", "size", "sample_count")
    about = (
        "原生 Generative Language API。gemini-*-image 走 :generateContent（可带多张参考图），"
        "imagen-* 走 :predict。也可填自建代理地址。"
    )

    def validate(self, req: GenRequest) -> None:
        super().validate(req)
        if not _model_path(req.model).startswith("imagen") and req.count > 1:
            raise Unsupported("Gemini 图像模型单次只返回一张，请把数量设为 1（或改用 Imagen）")
        if req.count > 4:
            raise Unsupported("Gemini 协议单次最多 4 张")
        if len(req.refs) > 14:
            raise Unsupported("Gemini 参考图最多 14 张")

    async def submit(self, ctx: ProviderContext) -> SubmitResult:
        req = ctx.request
        model = _model_path(req.model)
        headers = {**ctx.headers, "x-goog-api-key": ctx.api_key}
        aspect = req.params.get("aspect_ratio") or req.params.get("aspect")
        if model.startswith("imagen"):
            instances: list[dict[str, Any]] = [{"prompt": req.prompt}]
            if req.refs:
                raise Unsupported("Imagen 协议暂不支持参考图，请改用 gemini-*-image 模型")
            parameters: dict[str, Any] = {"sampleCount": max(1, req.count)}
            if aspect:
                parameters["aspectRatio"] = aspect
            resolution = str(req.params.get("resolution") or "").upper()
            if resolution in ("2K", "4K"):
                parameters["sampleImageSize"] = resolution
            resp = await ctx.client.post(
                ctx.url(f"/models/{model}:predict"),
                headers=headers,
                json={"instances": instances, "parameters": parameters},
                timeout=ctx.timeout,
            )
            raise_for_status(resp, "Imagen 生成")
            payload = parse_json(resp, "解析 Imagen 响应")
            outputs: list[Output] = []
            for item in payload.get("predictions") or []:
                raw = item.get("bytesBase64Encoded") or item.get("bytes_base64_encoded")
                if raw:
                    data = b64_bytes(raw)
                    outputs.append(Output(data=data, mime=mime_for("image", data=data)))
            if not outputs:
                raise ProviderError("Imagen 没有返回图片", kind="upstream")
            return SubmitResult(outputs=outputs)

        parts: list[dict[str, Any]] = [{"text": req.prompt}]
        for ref in req.refs:
            if not ref.data:
                continue
            parts.append(
                {
                    "inline_data": {
                        "mime_type": ref.mime or "image/png",
                        "data": base64.b64encode(ref.data).decode("ascii"),
                    }
                }
            )
        generation_config: dict[str, Any] = {"responseModalities": ["TEXT", "IMAGE"]}
        resolution = str(req.params.get("resolution") or "").upper()
        image_config: dict[str, Any] = {}
        if aspect:
            image_config["aspectRatio"] = aspect
        if resolution and resolution in ("2K", "4K"):
            image_config["imageSize"] = resolution
        if image_config:
            generation_config["imageConfig"] = image_config
        body = {"contents": [{"role": "user", "parts": parts}], "generationConfig": generation_config}
        resp = await ctx.client.post(
            ctx.url(f"/models/{model}:generateContent"),
            headers=headers,
            json=body,
            timeout=ctx.timeout,
        )
        raise_for_status(resp, "Gemini 生成")
        payload = parse_json(resp, "解析 Gemini 响应")
        outputs = []
        for part in _parts_payload(payload):
            inline = part.get("inlineData") or part.get("inline_data") or {}
            raw = inline.get("data")
            if raw:
                data = b64_bytes(raw)
                outputs.append(Output(data=data, mime=inline.get("mimeType") or mime_for("image", data=data)))
        if not outputs:
            text = " ".join(
                part.get("text", "") for part in _parts_payload(payload) if part.get("text")
            )
            reason = pick(payload, "promptFeedback.blockReason") or text[:200]
            raise ProviderError(
                f"Gemini 没有返回图片{('：' + str(reason)) if reason else ''}",
                kind="content" if reason else "upstream",
                retryable=False,
            )
        return SubmitResult(outputs=outputs)


class GeminiVideoAdapter(Adapter):
    protocol = "gemini_video"
    label = "Google Veo 视频"
    modalities = {"video"}
    supports_reference = True
    supports_video = True
    param_keys = ("aspect_ratio", "duration", "resolution", "negative_prompt")
    about = (
        "Veo 的 predictLongRunning 长任务协议：提交后返回 operation 名称，轮询直至 done，"
        "再下载生成的视频 URI。支持一张首帧参考图。"
    )

    def validate(self, req: GenRequest) -> None:
        super().validate(req)
        if req.count != 1:
            raise Unsupported("视频任务每次只能生成一个")
        if len(req.refs) > 1:
            raise Unsupported("Veo 一次只接受一张首帧参考图")

    async def submit(self, ctx: ProviderContext) -> SubmitResult:
        req = ctx.request
        model = _model_path(req.model)
        headers = {**ctx.headers, "x-goog-api-key": ctx.api_key}
        instance: dict[str, Any] = {"prompt": req.prompt}
        if req.negative:
            instance["negativePrompt"] = req.negative
        if req.refs:
            ref = req.refs[0]
            if not ref.data:
                raise ProviderError("首帧参考图内容为空", kind="params", retryable=False)
            instance["image"] = {
                "bytesBase64Encoded": base64.b64encode(ref.data).decode("ascii"),
                "mimeType": ref.mime or "image/png",
            }
        parameters: dict[str, Any] = {"sampleCount": 1}
        if req.params.get("aspect_ratio"):
            parameters["aspectRatio"] = req.params["aspect_ratio"]
        duration = req.params.get("duration")
        if duration:
            try:
                parameters["durationSeconds"] = int(float(duration))
            except (TypeError, ValueError):
                pass
        if req.params.get("resolution"):
            parameters["resolution"] = req.params["resolution"]
        resp = await ctx.client.post(
            ctx.url(f"/models/{model}:predictLongRunning"),
            headers=headers,
            json={"instances": [instance], "parameters": parameters},
            timeout=ctx.timeout,
        )
        raise_for_status(resp, "Veo 提交")
        payload = parse_json(resp, "解析 Veo 任务")
        name = payload.get("name")
        if not name:
            raise ProviderError("Veo 没有返回任务名称", kind="upstream")
        return SubmitResult(upstream_id=str(name), poll_after=6.0, raw=payload)

    async def poll(self, ctx: ProviderContext, handle: SubmitResult) -> PollResult:
        headers = {**ctx.headers, "x-goog-api-key": ctx.api_key}
        resp = await ctx.client.get(
            ctx.url(f"/{handle.upstream_id}"), headers=headers, timeout=60
        )
        raise_for_status(resp, "查询 Veo 任务")
        payload = parse_json(resp, "解析 Veo 任务")
        if payload.get("error"):
            error = payload["error"]
            message = error.get("message") if isinstance(error, dict) else str(error)
            return PollResult(failed=True, error=message or "Veo 任务失败")
        if not payload.get("done"):
            progress = float(pick(payload, "metadata.progressPercent") or 0) / 100
            return PollResult(progress=max(0.05, progress), raw=payload)
        response = payload.get("response") or {}
        uri = (
            pick(response, "generateVideoResponse.generatedSamples.0.video.uri")
            or pick(response, "generatedVideos.0.video.uri")
            or pick(response, "videos.0.uri")
            or pick(response, "predictions.0.videoUri")
        )
        if not uri:
            raise ProviderError("Veo 已完成但没有返回视频地址", kind="upstream")
        url = uri if "key=" in uri else f"{uri}{'&' if '?' in uri else '?'}key={ctx.api_key}"
        data = await self.fetch_bytes(ctx, url)
        return PollResult(done=True, outputs=[Output(data=data, kind="video", mime="video/mp4")], progress=1.0, raw=payload)


class GeminiTextAdapter(Adapter):
    """Optional helper for prompt rewriting (not used for media)."""

    protocol = "gemini_text"
    label = "Google Gemini 文本"
    modalities = {"text"}
    param_keys = ("temperature",)
    about = "用于提示词润色/翻译的文本模型接入。"
