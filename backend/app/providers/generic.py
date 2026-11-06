"""Config-driven adapter for bespoke / relay endpoints.

A route can carry a small JSON "recipe" describing how to build the request and
how to read the response, so a new vendor usually needs zero code:

{
  "path": "/v1/images/generations",
  "body": {"model": "{{model}}", "prompt": "{{prompt}}", "n": "{{count}}", "size": "{{size}}"},
  "refs": {"mode": "data_url", "field": "image"},          // optional
  "response": {"items": "data", "url": "url", "b64": "b64_json"},
  "poll": {"path": "/v1/tasks/{{id}}", "status": "status",
           "success": ["succeeded"], "failure": ["failed"],
           "items": "output", "url": "url", "b64": "b64_json"}   // optional
}

Supported placeholders inside strings: {{prompt}} {{negative}} {{model}}
{{count}} {{size}} {{aspect}} {{seed}} {{duration}} {{id}} {{base_url}}.
"""

from __future__ import annotations

import base64
import copy
import json
from typing import Any

from ..errors import ProviderError, Unsupported
from .base import (
    Adapter,
    GenRequest,
    Output,
    PollResult,
    ProviderContext,
    SubmitResult,
    absolute_url,
    b64_bytes,
    data_url,
    image_size,
    mime_for,
    parse_json,
    pick,
    raise_for_status,
)

DEFAULT_CONFIG: dict[str, Any] = {
    "path": "/v1/images/generations",
    "body": {
        "model": "{{model}}",
        "prompt": "{{prompt}}",
        "n": "{{count}}",
        "size": "{{size}}",
    },
    "response": {"items": "data", "url": "url", "b64": "b64_json"},
}

PLACEHOLDERS = (
    "prompt",
    "negative",
    "model",
    "count",
    "size",
    "aspect",
    "seed",
    "duration",
    "resolution",
    "id",
)


def _substitute(value: Any, mapping: dict[str, Any]) -> Any:
    if isinstance(value, str):
        exact = value[2:-2] if value.startswith("{{") and value.endswith("}}") else None
        if exact and exact in mapping:
            return mapping[exact]
        for key, replacement in mapping.items():
            if f"{{{{{key}}}}}" in value:
                value = value.replace(f"{{{{{key}}}}}", str(replacement))
        return value
    if isinstance(value, list):
        return [_substitute(item, mapping) for item in value]
    if isinstance(value, dict):
        return {key: _substitute(item, mapping) for key, item in value.items()}
    return value


def _collect(config: dict[str, Any], payload: dict[str, Any], kind: str, base_url: str | None = None) -> list[Output]:
    response = config.get("response") or {}
    path = response.get("items", "data")
    items = pick(payload, path, payload)
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        items = [payload]
    outputs: list[Output] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        b64_path = response.get("b64")
        url_path = response.get("url")
        raw = pick(item, b64_path) if b64_path else None
        url = pick(item, url_path) if url_path else None
        if isinstance(raw, str) and raw:
            data = b64_bytes(raw)
            outputs.append(Output(data=data, kind=kind, mime=mime_for(kind, data=data)))
        elif isinstance(url, str) and url.strip():
            final_url = absolute_url(base_url, url.strip()) if base_url else url.strip()
            outputs.append(Output(url=final_url, kind=kind, mime=mime_for(kind, url=final_url)))
    return outputs


class GenericAdapter(Adapter):
    protocol = "generic"
    label = "自定义 JSON 接口"
    modalities = {"image", "video"}
    supports_reference = True
    supports_video = True
    param_keys = ("size", "aspect", "seed", "duration", "resolution", "quality")
    about = "用一份 JSON 模板描述任意 HTTP 接口：请求体、响应字段、可选轮询任务。"

    def _config(self, ctx: ProviderContext) -> dict[str, Any]:
        config = (ctx.overrides or {}).get("generic") or (ctx.overrides or {}).get("template")
        if not config:
            raise Unsupported("该线路缺少自定义接口模板，请在模型线路中填写")
        return config

    def validate(self, req: GenRequest) -> None:
        super().validate(req)

    def _mapping(self, ctx: ProviderContext) -> dict[str, Any]:
        req = ctx.request
        aspect = req.params.get("aspect_ratio", req.params.get("aspect", ""))
        resolution = req.params.get("resolution", "")
        size = req.params.get("size", "")
        if ctx.modality == "image" and not size:
            size = image_size(str(aspect or "1:1"), str(resolution or "1K"))
        return {
            "prompt": req.prompt,
            "negative": req.negative,
            "model": req.model,
            "count": req.count,
            "size": size,
            "aspect": aspect,
            "resolution": resolution,
            "seed": req.params.get("seed", ""),
            "duration": req.params.get("duration", req.params.get("seconds", "")),
            "base_url": ctx.base_url,
        }

    def _headers(self, ctx: ProviderContext, config: dict[str, Any]) -> dict[str, str]:
        headers = {**ctx.headers, "Authorization": f"Bearer {ctx.api_key}"}
        style = config.get("auth_header", "bearer")
        if style == "x-api-key":
            headers["x-api-key"] = ctx.api_key
            headers.pop("Authorization", None)
        elif style == "none":
            headers.pop("Authorization", None)
        return headers

    async def submit(self, ctx: ProviderContext) -> SubmitResult:
        config = self._config(ctx)
        mapping = self._mapping(ctx)
        body = _substitute(copy.deepcopy(config.get("body", {})), mapping)
        if req_refs := ctx.request.refs:
            spec = config.get("refs") or {}
            mode = spec.get("mode", "data_url")
            field = spec.get("field", "image")
            images = [
                data_url(ref.mime or "image/png", ref.data)
                for ref in req_refs
                if ref.data
            ]
            if images:
                if mode == "b64":
                    body[field] = [ref.data for ref in req_refs if ref.data]
                elif mode == "data_url_array":
                    body[field] = images
                else:
                    body[field] = images[0] if len(images) == 1 else images
        headers = self._headers(ctx, config)
        path = str(config.get("path") or DEFAULT_CONFIG["path"])
        method = str(config.get("method", "POST")).upper()
        kwargs: dict[str, Any] = {"headers": headers, "timeout": ctx.timeout}
        if method in ("GET", "DELETE"):
            kwargs["params"] = body
        else:
            kwargs["json"] = body
        resp = await ctx.client.request(method, ctx.url(path), **kwargs)
        raise_for_status(resp, "自定义接口请求")
        if config.get("response", {}).get("mode") == "binary":
            return SubmitResult(
                outputs=[Output(data=resp.content, mime=resp.headers.get("content-type", "image/png"),
                                kind="video" if "video" in resp.headers.get("content-type", "") else "image")]
            )
        payload = parse_json(resp, "解析自定义接口响应")
        response = config.get("response") or {}
        job_id_path = response.get("id")
        job_id = pick(payload, job_id_path) if job_id_path else None
        poll = config.get("poll") or {}
        if job_id and poll:
            return SubmitResult(upstream_id=str(job_id), poll_after=float(poll.get("interval", 3)), raw=payload)
        outputs = _collect(config, payload, "video" if ctx.modality == "video" else "image", base_url=ctx.base_url)
        if not outputs:
            message = pick(payload, response.get("error", "error")) or payload.get("message") or ""
            raise ProviderError(
                f"接口没有返回可用结果{('：' + str(message)) if message else ''}",
                kind="upstream",
            )
        for output in outputs:
            if output.url and not output.data:
                try:
                    output.data = await self.fetch_bytes(ctx, output.url)
                    output.url = None
                except ProviderError:
                    pass
        return SubmitResult(outputs=outputs)

    async def poll(self, ctx: ProviderContext, handle: SubmitResult) -> PollResult:
        config = self._config(ctx)
        poll = config.get("poll") or {}
        path = str(poll.get("path", "")).replace("{{id}}", str(handle.upstream_id))
        if not path:
            raise ProviderError("自定义接口缺少轮询路径", kind="params", retryable=False)
        headers = self._headers(ctx, config)
        resp = await ctx.client.get(ctx.url(path), headers=headers, timeout=60)
        raise_for_status(resp, "查询自定义任务")
        payload = parse_json(resp, "解析自定义任务")
        status = str(pick(payload, poll.get("status", "status"), "")).lower()
        success = {str(v).lower() for v in poll.get("success", ["succeeded", "completed", "done"])}
        failure = {str(v).lower() for v in poll.get("failure", ["failed", "error", "cancelled"])}
        if status in failure:
            message = pick(payload, poll.get("error", "error.message")) or payload.get("message") or status
            return PollResult(failed=True, error=str(message))
        if status in success:
            merged = {
                **config,
                "response": {
                    **(config.get("response") or {}),
                    **{key: poll[key] for key in ("items", "url", "b64") if key in poll},
                },
            }
            merged["response"].setdefault("items", "data")
            outputs = _collect(merged, payload, "video" if ctx.modality == "video" else "image", base_url=ctx.base_url)
            for output in outputs:
                if output.url and not output.data:
                    try:
                        output.data = await self.fetch_bytes(ctx, output.url)
                        output.url = None
                    except ProviderError:
                        pass
            return PollResult(done=True, outputs=outputs, progress=1.0, raw=payload)
        raw_progress = pick(payload, poll.get("progress", "progress"), 0)
        try:
            value = float(raw_progress)
            progress = value / 100 if value > 1 else value
        except (TypeError, ValueError):
            progress = 0.2
        return PollResult(progress=max(0.05, min(progress, 0.95)), raw=payload)
