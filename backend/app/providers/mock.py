"""Offline mock provider: lets the whole pipeline be exercised without keys."""

from __future__ import annotations

import asyncio
import hashlib
import io
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..errors import Unsupported
from .base import Adapter, GenRequest, Output, ProviderContext, SubmitResult

FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/segoeui.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _wrap(text: str, width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        line = ""
        for char in paragraph:
            if char == "\n":
                lines.append(line)
                line = ""
                continue
            if len(line) >= width:
                lines.append(line)
                line = ""
            line += char
        lines.append(line)
    return lines[:8]


def _palette(seed: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    a = (40 + digest[0] % 120, 40 + digest[1] % 120, 60 + digest[2] % 140)
    b = (10 + digest[3] % 40, 10 + digest[4] % 40, 16 + digest[5] % 40)
    return a, b


def render_mock_image(prompt: str, model: str, size: str | None, index: int = 0) -> bytes:
    width, height = 1024, 1024
    if size and "x" in size:
        try:
            width, height = (int(part) for part in size.lower().split("x", 1))
        except ValueError:
            pass
    width, height = max(256, min(width, 2048)), max(256, min(height, 2048))
    a, b = _palette(prompt + model + str(index))
    image = Image.new("RGB", (width, height), b)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        ratio = y / max(height - 1, 1)
        color = tuple(int(a[i] * (1 - ratio) + b[i] * ratio) for i in range(3))
        draw.line([(0, y), (width, y)], fill=color)
    margin = int(min(width, height) * 0.07)
    draw.rectangle(
        [margin, margin, width - margin, height - margin],
        outline=(255, 255, 255, 90),
        width=max(2, int(min(width, height) * 0.003)),
    )
    draw.text((margin * 1.4, margin * 1.3), "OneFrame", font=_font(max(18, width // 26)), fill=(255, 255, 255))
    draw.text(
        (margin * 1.4, margin * 2.1),
        f"mock · {model}",
        font=_font(max(12, width // 48)),
        fill=(255, 255, 255),
    )
    y = int(height * 0.52)
    for line in _wrap(prompt.strip() or "未填写提示词", max(12, width // 42)):
        draw.text((margin * 1.4, y), line, font=_font(max(14, width // 34)), fill=(255, 255, 255))
        y += int(max(14, width // 34) * 1.35)
    draw.text(
        (margin * 1.4, height - margin * 1.8),
        f"{width} × {height}",
        font=_font(max(10, width // 60)),
        fill=(230, 230, 230),
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class MockAdapter(Adapter):
    protocol = "mock"
    label = "离线演示"
    modalities = {"image", "video"}
    supports_reference = True
    supports_video = True
    param_keys = ("size", "aspect_ratio", "duration")
    about = "不需要任何密钥，用于体验完整流程与接口联调。"

    def validate(self, req: GenRequest) -> None:
        super().validate(req)
        if req.params.get("mock_fail"):
            raise Unsupported("演示用的失败参数")

    async def submit(self, ctx: ProviderContext) -> SubmitResult:
        req = ctx.request
        await asyncio.sleep(float(ctx.overrides.get("delay", 1.2)))
        if ctx.modality == "video":
            png = render_mock_image(req.prompt + " · video", req.model, "768x768")
            data = await asyncio.to_thread(_png_to_mp4, png, float(req.params.get("duration", 3)))
            return SubmitResult(
                outputs=[Output(data=data, kind="video", mime="video/mp4")],
                external_url=None,
            )
        outputs = [
            Output(
                data=await asyncio.to_thread(
                    render_mock_image, req.prompt, req.model, req.params.get("size"), index
                ),
                mime="image/png",
            )
            for index in range(min(req.count, 8))
        ]
        return SubmitResult(outputs=outputs)


def _png_to_mp4(png: bytes, seconds: float) -> bytes:
    from ..core.storage import media_tool

    ffmpeg = media_tool("ffmpeg")
    if not ffmpeg:
        raise Unsupported("本机缺少 ffmpeg，无法生成演示视频（图片生成不受影响）")
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "frame.png"
        target = Path(tmp) / "out.mp4"
        source.write_bytes(png)
        command = [
            ffmpeg, "-y", "-loop", "1", "-i", str(source),
            "-t", f"{max(1.0, seconds):.1f}", "-r", "24",
            "-vf", "scale=768:768,format=yuv420p",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-movflags", "+faststart",
            str(target),
        ]
        try:
            subprocess.run(command, capture_output=True, timeout=120, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            raise Unsupported(f"演示视频编码失败：{exc}") from exc
        if not target.exists():
            raise Unsupported("演示视频编码失败，请检查 ffmpeg 安装")
        return target.read_bytes()
