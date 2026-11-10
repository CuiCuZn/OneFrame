"""OpenAI Images compatible protocol (``/images/generations`` + ``/images/edits``).

This is the lingua franca of relay/aggregator services: one adapter covers
official OpenAI, most Chinese relays and many self-hosted gateways.
"""

from __future__ import annotations

from ..errors import ProviderError, Unsupported
from .base import (
    Adapter,
    GenRequest,
    Output,
    ProviderContext,
    SubmitResult,
    absolute_url,
    b64_bytes,
    image_size,
    mime_for,
    parse_json,
    pick,
    raise_for_status,
)


def _extract_images(payload: dict, kind: str = "image", base_url: str | None = None) -> list[Output]:
    """Tolerant response parsing: data[] / images[] / output[] + b64 or url (relative or absolute)."""

    items = payload.get("data") or payload.get("images") or payload.get("output") or []
    if isinstance(items, dict):
        items = [items]
    outputs: list[Output] = []
    for item in items:
        if isinstance(item, str) and item.strip():
            final_url = absolute_url(base_url, item.strip()) if base_url else item.strip()
            outputs.append(Output(url=final_url, kind=kind, mime=mime_for(kind, url=final_url)))
            continue
        if not isinstance(item, dict):
            continue
        b64 = item.get("b64_json") or item.get("base64") or item.get("image_base64")
        url = item.get("url") or item.get("image_url") or item.get("image")
        if b64:
            data = b64_bytes(b64)
            outputs.append(Output(data=data, kind=kind, mime=mime_for(kind, data=data)))
        elif isinstance(url, str) and url.strip():
            final_url = absolute_url(base_url, url.strip()) if base_url else url.strip()
            outputs.append(Output(url=final_url, kind=kind, mime=mime_for(kind, url=final_url)))
    return outputs


class OpenAIImagesAdapter(Adapter):
    protocol = "openai_image"
    label = "OpenAI Images 兼容"
    modalities = {"image"}
    supports_reference = True
    supports_mask = True
    param_keys = ("size", "quality", "background", "style", "seed", "response_format")
    about = (
        "标准 /v1/images/generations 与 /v1/images/edits（multipart）。适合 OpenAI 官方"
        "以及绝大多数中转/聚合站；支持 b64_json 与 url 两种返回。"
    )

    def _response_format(self, ctx: ProviderContext) -> str:
        # Relays frequently implement only one of the two formats; default to
        # "url" because that is what most aggregation gateways accept.
        value = str(ctx.overrides.get("response_format") or "url").lower()
        return value if value in ("url", "b64_json") else "url"

    def validate(self, req: GenRequest) -> None:
        super().validate(req)
        if req.count > 16:
            raise Unsupported("单次最多生成 16 张")
        if len(req.refs) > 16:
            raise Unsupported("参考图最多 16 张")
        if req.mask:
            if len(req.refs) != 1:
                raise Unsupported("局部重绘需要且只需要一张源图")
            if req.count != 1:
                raise Unsupported("局部重绘每次只能生成一张")

    async def submit(self, ctx: ProviderContext) -> SubmitResult:
        req = ctx.request
        params = req.params
        headers = {"Authorization": f"Bearer {ctx.api_key}", **ctx.headers}
        response_format = self._response_format(ctx)
        size = params.get("size") or (
            "" if req.mask else image_size(
                str(params.get("aspect_ratio") or "1:1"),
                str(params.get("resolution") or "1K"),
            )
        )
        quality = params.get("quality") or ""

        if req.refs or req.mask:
            files: list[tuple[str, tuple[str, bytes, str]]] = []
            for index, ref in enumerate(req.refs):
                if not ref.data:
                    raise ProviderError("参考图内容为空", kind="params", retryable=False)
                field = "image[]" if len(req.refs) > 1 else "image"
                files.append((field, (f"ref-{index}.png", ref.data, ref.mime or "image/png")))
            if req.mask and req.mask.data:
                files.append(("mask", ("mask.png", req.mask.data, "image/png")))
            form: dict[str, str] = {"model": req.model, "prompt": req.prompt}
            if req.negative:
                form["negative_prompt"] = req.negative
            if size:
                form["size"] = size
            if quality:
                form["quality"] = quality
            if req.count > 1:
                form["n"] = str(req.count)
            form["response_format"] = response_format
            resp = await ctx.client.post(
                ctx.url("/images/edits"),
                headers=headers,
                data=form,
                files=files,
                timeout=ctx.timeout,
            )
        else:
            body = {
                "model": req.model,
                "prompt": req.prompt,
                "n": req.count,
                "response_format": response_format,
            }
            if req.negative:
                body["negative_prompt"] = req.negative
            if size:
                body["size"] = size
            if quality:
                body["quality"] = quality
            for key in ("background", "style", "seed", "moderation"):
                if params.get(key) not in (None, ""):
                    body[key] = params[key]
            resp = await ctx.client.post(
                ctx.url("/images/generations"), headers=headers, json=body, timeout=ctx.timeout
            )

        raise_for_status(resp, "图片生成")
        payload = parse_json(resp, "解析图片响应")
        outputs = _extract_images(payload, base_url=ctx.base_url)
        if not outputs:
            # Some relays wrap the payload one level deeper.
            for key in ("result", "response"):
                nested = payload.get(key)
                if isinstance(nested, dict):
                    outputs = _extract_images(nested, base_url=ctx.base_url)
                    if outputs:
                        break
                if isinstance(nested, list):
                    outputs = _extract_images({"data": nested}, base_url=ctx.base_url)
                    if outputs:
                        break
        if not outputs:
            reason = pick(payload, "error.message") or payload.get("message") or ""
            raise ProviderError(
                f"图片服务没有返回可用结果{('：' + str(reason)) if reason else ''}",
                kind="upstream",
            )
        for output in outputs:
            if output.url and not output.data:
                try:
                    output.data = await self.fetch_bytes(ctx, output.url)
                    output.mime = mime_for("image", data=output.data)
                    output.url = None
                except ProviderError:
                    # Keep the URL: the worker downloads it after the job is accepted,
                    # so a CDN hiccup never triggers a second paid generation.
                    pass
        final_outputs = (
            outputs[: req.count]
            if (req.count and req.count > 1 and len(outputs) > req.count)
            else outputs
        )
        return SubmitResult(outputs=final_outputs)
