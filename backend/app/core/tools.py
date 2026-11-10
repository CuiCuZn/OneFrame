"""Server-owned prompts for creative tools.

Every tool reuses the normal generation pipeline; only the prompt and the
capability checks live here.  Keeping them on the server means the UI cannot
silently change the core instruction, and the job snapshot records exactly
what was sent.
"""

from __future__ import annotations

from typing import Any

from ..errors import Unsupported

TOOLS = {"extract_costume", "refine", "inpaint", "character"}

EXTRACT_COSTUME_PROMPT = """Extract the complete outfit from the attached image into a clean clothing reference on a plain white background.
Show only the garments, shoes and outfit accessories, arranged as an unobstructed, front-facing flat lay or invisible-body product display.
Remove the person, face, hair, skin, body parts, mannequin and original background. Do not include any human figure.
Preserve the original garment design, silhouette, proportions, colors, fabric texture, patterns and decorative details as faithfully as possible.
Keep all visible outfit pieces together in one image. Do not invent additional clothing or accessories. No text, labels, logos added or borders."""

REFINE_PROMPT = """Refine the attached image without changing its subject, pose, clothing, framing or composition.
Improve micro-detail, skin and material texture, lighting balance, edge clarity and overall photographic quality.
Keep the same person and identity. Do not add or remove objects, do not change the background, and do not restyle the image.
No text, logos or watermarks."""

CHARACTER_VIEWS = {
    "front": "front view, looking straight at the camera",
    "three_quarter": "three-quarter view, nose toward the left, both eyes visible",
    "profile_left": "strict left profile, nose toward the left, only one eye visible",
    "profile_right": "strict right profile, nose toward the right, only one eye visible",
    "back": "back view, no face visible, showing the back of the hair and outfit",
}

CHARACTER_EXPRESSIONS = {
    "neutral": "calm and neutral, relaxed mouth, soft gaze",
    "happy": "natural smile, corners of the mouth lifted, warm eyes",
    "sad": "sad and low, eyebrows slightly down, mouth corners down",
    "angry": "controlled anger, brows tightened, firm gaze, no exaggerated distortion",
    "surprised": "surprised, eyebrows raised, eyes wide, lips slightly parted",
    "serious": "serious and focused, lips naturally closed, steady gaze",
}

CHARACTER_SHEET_PROMPT = """Create a single character turnaround sheet of the same person from the attached reference.
Show four full-body views in one image, left to right: front, three-quarter, side and back.
Keep identity, face shape, features, hairstyle, hair color, skin tone, body proportions and outfit identical across all four views.
Neutral expression, clean solid background, even studio lighting, no text, no labels, no watermark."""


def character_prompt(options: dict[str, Any]) -> str:
    mode = str(options.get("mode") or "view")
    preset = str(options.get("preset") or "front")
    if mode == "sheet":
        return CHARACTER_SHEET_PROMPT
    if mode == "view":
        view = CHARACTER_VIEWS.get(preset)
        if not view:
            raise Unsupported("不支持的角色视角")
        return (
            f"Show the same person from the attached reference in a {view}. "
            "Keep identity, face shape, features, hairstyle, hair color and skin tone identical. "
            "Clean neutral background, single person, single frame, no text or watermark."
        )
    if mode == "expression":
        expression = CHARACTER_EXPRESSIONS.get(preset)
        if not expression:
            raise Unsupported("不支持的角色表情")
        return (
            f"Show the same person from the attached reference with this expression: {expression}. "
            "Keep identity, face shape, features, hairstyle, hair color and skin tone identical. "
            "Keep the same outfit and background, single person, single frame, no text or watermark."
        )
    raise Unsupported("不支持的角色模式")


def build_prompt(tool: str, options: dict[str, Any], user_prompt: str = "") -> str:
    extra = (user_prompt or "").strip()
    if tool == "extract_costume":
        prompt = EXTRACT_COSTUME_PROMPT
    elif tool == "refine":
        prompt = REFINE_PROMPT
    elif tool == "inpaint":
        prompt = extra
        if not prompt:
            raise Unsupported("局部重绘需要描述要修改的内容")
    elif tool == "character":
        prompt = character_prompt(options)
    else:
        raise Unsupported("未知的创作工具")
    if extra and tool != "inpaint":
        prompt = f"{prompt}\nAdditional requirement: {extra}"
    return prompt


def validate_tool(
    tool: str,
    options: dict[str, Any],
    model: dict[str, Any],
    adapter: Any,
    ref_count: int,
) -> None:
    if tool not in TOOLS:
        raise Unsupported("未知的创作工具")
    if model.get("modality") != "image":
        raise Unsupported("该工具只支持图像模型")
    if not options.get("source_asset_id"):
        raise Unsupported("缺少源图片")
    if ref_count > int(model.get("caps", {}).get("max_refs", 0)):
        raise Unsupported("当前模型参考图数量不足")
    if tool == "inpaint":
        if "inpaint" not in model.get("caps", {}).get("features", []):
            raise Unsupported("当前模型未开启局部重绘能力")
        if not getattr(adapter, "supports_mask", False):
            raise Unsupported("当前协议不支持蒙版局部重绘")
    elif not getattr(adapter, "supports_reference", False):
        raise Unsupported("当前协议不支持参考图")
    if tool == "character":
        character_prompt(options)
