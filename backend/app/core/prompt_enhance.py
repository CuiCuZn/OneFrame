"""Deterministic local prompt enhancement.

This is deliberately rule-based: no text model, no hidden rewriting.  It adds
camera/lighting/quality constraints around the user's own description and is
safe to run offline.
"""

from __future__ import annotations

from typing import Any

from .prompt import DEFAULT_NEGATIVE, STYLE_BY_ID

IMAGE_LINES = {
    "zh": "构图与画质：主体清晰，画面完整，边缘干净，材质与纹理真实，避免畸形与多余肢体。",
    "en": "Composition and quality: clear subject, complete framing, clean edges, realistic materials and texture, no distorted anatomy or extra limbs.",
}

VIDEO_LINES = {
    "zh": "镜头与运动：主体动作连贯，机位稳定，运动方向明确，避免跳切与形变。",
    "en": "Camera and motion: coherent subject motion, stable camera, clear movement direction, no jump cuts or morphing.",
}

REFERENCE_LINES = {
    "zh": "参考一致性：人物、服装与姿势以参考图为准，只取指定特征，不复制参考图背景。",
    "en": "Reference consistency: follow the reference images for identity, costume and pose; take only the specified traits and do not copy their backgrounds.",
}


def enhance(payload: dict[str, Any]) -> dict[str, Any]:
    language = "en" if payload.get("language") == "en" else "zh"
    prompt = str(payload.get("prompt") or "").strip()
    modality = payload.get("modality") or "image"
    style = STYLE_BY_ID.get(str(payload.get("style") or "none"), STYLE_BY_ID["none"])
    notes: list[str] = []
    lines = [prompt]

    style_text = style["zh"] if language == "zh" else style["en"]
    if style_text and style_text not in prompt:
        lines.append(("风格：" if language == "zh" else "Style: ") + style_text)
        notes.append("补充了风格约束" if language == "zh" else "Added style constraints")

    if modality == "video":
        lines.append(VIDEO_LINES[language])
        notes.append("补充了镜头与运动约束" if language == "zh" else "Added camera and motion guidance")
    else:
        lines.append(IMAGE_LINES[language])
        notes.append("补充了构图与画质约束" if language == "zh" else "Added composition and quality guidance")

    if payload.get("has_refs"):
        lines.append(REFERENCE_LINES[language])
        notes.append("补充了参考一致性约束" if language == "zh" else "Added reference consistency guidance")

    negative = str(payload.get("negative") or "").strip() or DEFAULT_NEGATIVE
    return {
        "prompt": "\n".join(line for line in lines if line.strip()),
        "negative": negative,
        "notes": notes,
        "style": style["id"],
        "source": "rules",
        "model": "",
    }
