"""Protocol adapter contract shared by every provider implementation."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx

from ..errors import ProviderError, Unsupported

Modality = Literal["image", "video"]


@dataclass
class RefImage:
    name: str = "reference"
    mime: str = "image/png"
    data: bytes | None = None
    role: str = "reference"  # reference | first_frame | last_frame | style
    width: int | None = None
    height: int | None = None


@dataclass
class GenRequest:
    model: str
    prompt: str
    negative: str = ""
    refs: list[RefImage] = field(default_factory=list)
    count: int = 1
    params: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.params.get(key, default)


@dataclass
class ProviderContext:
    client: httpx.AsyncClient
    base_url: str
    api_key: str
    headers: dict[str, str]
    request: GenRequest
    overrides: dict[str, Any] = field(default_factory=dict)
    modality: str = "image"
    timeout: float = 180.0

    def url(self, path: str) -> str:
        return self.base_url.rstrip("/") + "/" + path.lstrip("/")


@dataclass
class Output:
    data: bytes | None = None
    url: str | None = None
    mime: str = "image/png"
    kind: Modality = "image"
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class SubmitResult:
    """Either finished synchronously (outputs) or an upstream job id to poll."""

    outputs: list[Output] = field(default_factory=list)
    upstream_id: str | None = None
    poll_after: float = 2.0
    raw: dict[str, Any] = field(default_factory=dict)
    external_url: str | None = None

    @property
    def done(self) -> bool:
        return self.upstream_id is None


@dataclass
class PollResult:
    done: bool = False
    outputs: list[Output] = field(default_factory=list)
    failed: bool = False
    error: str = ""
    progress: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)
    external_url: str | None = None


class Adapter:
    protocol: str = ""
    label: str = ""
    modalities: set[str] = {"image"}
    supports_reference: bool = False
    supports_video: bool = False
    # Parameter keys this adapter understands (used for the model editor).
    param_keys: tuple[str, ...] = ()
    # Public description shown in the UI.
    about: str = ""

    def validate(self, req: GenRequest) -> None:
        if req.count < 1:
            raise Unsupported("生成数量至少为 1")
        if req.refs and not self.supports_reference:
            raise Unsupported("该协议不支持参考图")

    async def submit(self, ctx: ProviderContext) -> SubmitResult:  # pragma: no cover
        raise NotImplementedError

    async def poll(self, ctx: ProviderContext, handle: SubmitResult) -> PollResult:
        raise NotImplementedError

    async def cancel(self, ctx: ProviderContext, handle: SubmitResult) -> None:
        return None

    # ── helpers ────────────────────────────────────────────────────────────
    async def fetch_bytes(self, ctx: ProviderContext, url: str) -> bytes:
        try:
            resp = await ctx.client.get(url, timeout=ctx.timeout)
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"下载生成结果失败：{type(exc).__name__}", kind="network", retryable=True
            ) from exc
        if resp.status_code >= 400:
            raise ProviderError(
                f"下载生成结果失败（HTTP {resp.status_code}）", kind="upstream"
            )
        data = resp.content
        if not data:
            raise ProviderError("上游返回了空的生成结果", kind="upstream")
        return data


ASPECT_RATIOS: dict[str, tuple[int, int]] = {
    "1:1": (1, 1),
    "4:3": (4, 3),
    "3:4": (3, 4),
    "16:9": (16, 9),
    "9:16": (9, 16),
}

IMAGE_RESOLUTIONS: dict[str, int] = {"1K": 1024, "2K": 2048, "4K": 4096}


def absolute_url(base_url: str | None, url: str) -> str:
    """Resolve a possibly relative URL against the provider base_url."""
    if not url:
        return ""
    url = url.strip()
    if url.startswith(("http://", "https://", "data:")):
        return url
    if not base_url:
        return url
    parts = urlsplit(base_url)
    if url.startswith("/"):
        return f"{parts.scheme}://{parts.netloc}{url}"
    return f"{base_url.rstrip('/')}/{url.lstrip('/')}"


def image_size(aspect: str = "1:1", resolution: str = "1K") -> str:
    """Derive a concrete pixel size from aspect ratio + 1K/2K/4K long edge."""

    ratio = ASPECT_RATIOS.get(str(aspect), ASPECT_RATIOS["1:1"])
    base = IMAGE_RESOLUTIONS.get(str(resolution).upper(), IMAGE_RESOLUTIONS["1K"])
    width, height = ratio
    scale = base / max(width, height)
    # Keep dimensions on an 8px grid so most providers accept them.
    out_w = max(256, int(round(width * scale / 8)) * 8)
    out_h = max(256, int(round(height * scale / 8)) * 8)
    return f"{out_w}x{out_h}"


def mime_for(kind: str, data: bytes | None = None, url: str | None = None) -> str:
    if kind == "video":
        return "video/mp4"
    if data and data[:4] == b"\x89PNG":
        return "image/png"
    if data and data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if data and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if url:
        lower = url.split("?")[0].lower()
        for ext, mime in ((".png", "image/png"), (".jpg", "image/jpeg"),
                          (".jpeg", "image/jpeg"), (".webp", "image/webp")):
            if lower.endswith(ext):
                return mime
    return "image/png"


def b64_bytes(value: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ProviderError("图片响应不是合法的 base64 数据", kind="upstream", retryable=False) from exc


def data_url(mime: str, payload: bytes) -> str:
    return f"data:{mime};base64,{base64.b64encode(payload).decode('ascii')}"


def raise_for_status(resp: httpx.Response, action: str = "请求") -> None:
    """Translate HTTP failures into routing-relevant ProviderError kinds."""

    if resp.status_code < 400:
        return
    text = resp.text[:600] if resp.text else ""
    status = resp.status_code
    if status in (401, 403):
        raise ProviderError(
            f"{action}鉴权失败（HTTP {status}）：{text}", kind="auth", status=status
        )
    if status == 429:
        raise ProviderError(
            f"{action}触发限流（HTTP 429）：{text}", kind="quota", status=status
        )
    if status in (400, 404, 409, 413, 422):
        raise ProviderError(
            f"{action}被拒绝（HTTP {status}）：{text}",
            kind="params",
            status=status,
            retryable=False,
        )
    if status in (500, 502, 503, 504):
        raise ProviderError(
            f"{action}上游异常（HTTP {status}）：{text}", kind="upstream", status=status
        )
    raise ProviderError(f"{action}失败（HTTP {status}）：{text}", kind="upstream", status=status)


def parse_json(resp: httpx.Response, action: str = "解析响应") -> dict:
    try:
        payload = resp.json()
    except ValueError as exc:
        snippet = (resp.text or "")[:300]
        raise ProviderError(
            f"{action}失败：上游返回了非 JSON 内容（{snippet}）",
            kind="upstream",
            retryable=False,
        ) from exc
    if not isinstance(payload, dict):
        raise ProviderError(f"{action}失败：响应结构不是对象", kind="upstream")
    return payload


def pick(payload: Any, path: str, default: Any = None) -> Any:
    """Tiny dotted-path picker used by the generic adapter: ``data.0.url``."""

    current = payload
    if not path:
        return current
    for part in path.split("."):
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return default
        elif isinstance(current, dict):
            if part not in current:
                return default
            current = current[part]
        else:
            return default
    return current
