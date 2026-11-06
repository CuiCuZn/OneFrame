"""Prompt engineering: style presets and the reference recipe compiler.

The compiler turns "which reference plays which role" into an explicit,
numbered instruction.  This is the single biggest quality lever for multi-image
models: telling the model *what to copy* and *what not to copy* per image.
"""

from __future__ import annotations

from typing import Any

ROLE_LABELS = {
    "character": ("人物外貌", "character identity"),
    "costume": ("服装造型", "costume"),
    "pose": ("姿势构图", "pose and framing"),
    "style": ("画面风格", "visual style"),
    "reference": ("参考图", "reference"),
}

STYLE_PRESETS: list[dict[str, Any]] = [
    {
        "id": "none",
        "name": "不加风格",
        "zh": "",
        "en": "",
    },
    {
        "id": "cinematic",
        "name": "电影感",
        "zh": "电影剧照质感，柔和体积光与浅景深，低饱和高动态范围，35mm 胶片颗粒，构图留白克制",
        "en": "cinematic still, soft volumetric light, shallow depth of field, low saturation, high dynamic range, subtle 35mm grain, restrained composition",
    },
    {
        "id": "photo",
        "name": "写实摄影",
        "zh": "写实摄影，85mm 人像镜头，自然光，皮肤质感真实，细节清晰，中景构图",
        "en": "realistic photography, 85mm portrait lens, natural light, authentic skin texture, crisp detail, medium shot",
    },
    {
        "id": "editorial",
        "name": "时尚大片",
        "zh": "高级时尚杂志大片，硬光与柔光结合，干净背景，轮廓光勾边，杂志封面构图",
        "en": "high fashion editorial, hard and soft light mix, clean backdrop, rim light, magazine cover composition",
    },
    {
        "id": "anime",
        "name": "日系动画",
        "zh": "日系动画赛璐璐上色，干净线稿，通透高光，柔和渐变天空，细腻发丝，TV 动画质感",
        "en": "Japanese anime cel shading, clean lineart, luminous highlights, soft gradient sky, detailed hair, TV anime quality",
    },
    {
        "id": "illustration",
        "name": "厚涂插画",
        "zh": "韩系半厚涂插画，笔触可见，丰富明暗层次，强对比色彩，精致面部刻画",
        "en": "semi-thick painterly illustration, visible brushwork, rich values, strong color contrast, refined facial rendering",
    },
    {
        "id": "3d",
        "name": "3D 渲染",
        "zh": "高质量 3D 渲染，PBR 材质，柔和全局光照，次表面散射皮肤，Octane 质感",
        "en": "high quality 3D render, PBR materials, soft global illumination, subsurface scattering skin, Octane look",
    },
    {
        "id": "watercolor",
        "name": "水彩手绘",
        "zh": "水彩手绘，纸纹肌理，湿画法晕染，留白自然，淡雅配色",
        "en": "watercolor painting, paper texture, wet-on-wet bleeding, natural white space, delicate palette",
    },
    {
        "id": "cyberpunk",
        "name": "赛博朋克",
        "zh": "赛博朋克夜景，雨夜霓虹，冷暖双色轮廓光，湿润地面反射，体积雾",
        "en": "cyberpunk night, neon rain, teal and magenta rim light, wet reflective ground, volumetric fog",
    },
    {
        "id": "ink",
        "name": "国风水墨",
        "zh": "中国水墨，宣纸质感，墨色浓淡层次，留白意境，工笔与写意结合",
        "en": "Chinese ink wash, rice paper texture, layered ink tones, negative space, fine-brush meets freehand",
    },
    {
        "id": "film",
        "name": "复古胶片",
        "zh": "复古胶片摄影，柯达 Portra 色调，轻微漏光，柔和高光溢出，暖色阴影",
        "en": "vintage film photography, Kodak Portra palette, slight light leak, soft highlight bloom, warm shadows",
    },
    {
        "id": "studio",
        "name": "棚拍白底",
        "zh": "纯白背景棚拍，均匀柔光箱照明，干净投影，电商级清晰度，全身构图",
        "en": "studio shot on pure white, even softbox lighting, clean shadow, e-commerce clarity, full body",
    },
    {
        "id": "concept",
        "name": "角色设定图",
        "zh": "角色设定图，正面全身站立，中性表情，清晰服装结构，干净纯色背景，概念设计稿",
        "en": "character concept sheet, front full-body standing, neutral expression, clear costume structure, clean solid background",
    },
    {
        "id": "noir",
        "name": "黑白硬光",
        "zh": "黑白摄影，强硬侧逆光，高对比，深黑阴影，戏剧化氛围",
        "en": "black and white photography, hard side-back light, high contrast, deep shadows, dramatic mood",
    },
]

STYLE_BY_ID = {item["id"]: item for item in STYLE_PRESETS}

DEFAULT_NEGATIVE = (
    "低质量, 模糊, 噪点, 变形的手, 多余手指, 肢体错位, 五官崩坏, 文字, 水印, 签名, logo"
)

QUALITY_LINES = {
    "zh": "输出单画面、单人物、单视角，不要拼贴、分镜、设定集或局部特写；画面中不要出现文字、标志与水印。",
    "en": "Single frame, single subject, single viewpoint. No collage, storyboard, character sheet or inset close-up. No text, logos or watermarks.",
}


def _label(role: str, language: str) -> str:
    zh, en = ROLE_LABELS.get(role, ROLE_LABELS["reference"])
    return zh if language == "zh" else en


def compile_recipe(payload: dict[str, Any]) -> dict[str, Any]:
    """Build a deterministic prompt from reference slots.

    payload: {refs:[{role,title}], style, extra, language, subject, quality}
    """

    language = "en" if payload.get("language") == "en" else "zh"
    refs = [ref for ref in payload.get("refs", []) if ref.get("role")]
    ordered_roles = ["character", "costume", "pose", "style", "reference"]
    refs = sorted(refs, key=lambda ref: ordered_roles.index(ref.get("role", "reference")))
    style = STYLE_BY_ID.get(payload.get("style", "none"), STYLE_BY_ID["none"])
    extra = str(payload.get("extra") or "").strip()
    subject = str(payload.get("subject") or "").strip()

    if not refs and not extra and not subject:
        return {"prompt": "", "negative": DEFAULT_NEGATIVE, "refs": []}

    lines: list[str] = []
    mapping: list[dict[str, Any]] = []
    if language == "zh":
        if refs:
            header = "、".join(f"图{i + 1} = {_label(ref['role'], 'zh')}" for i, ref in enumerate(refs))
            lines.append(f"参考图对应关系：{header}。")

        def first(role: str) -> int:
            for index, ref in enumerate(refs):
                if ref["role"] == role:
                    return index + 1
            return 0

        character_index = first("character")
        costume_index = first("costume")
        pose_index = first("pose")
        style_index = first("style")

        if character_index:
            lines.append(
                f"• 人物：以图{character_index}的人物为准，保持脸型、五官、发型、发色与整体气质一致。"
            )
        if subject:
            lines.append(f"• 人物设定：{subject}。" if not character_index else f"• 补充特征：{subject}。")
        if costume_index:
            lines.append(
                f"• 服装：让同一个人物穿上图{costume_index}中的整套服装与配饰，保留款式、颜色、材质与穿戴方式；"
                "不要复制其背景、陈列方式或模特外观。"
            )
        if pose_index:
            lines.append(
                f"• 姿势：参考图{pose_index}的肢体姿态、重心、镜头角度与构图；只取姿势，不复制其外貌与服饰。"
            )
        if style_index:
            lines.append(f"• 风格：参考图{style_index}的画面风格、色彩与光影，不复制其中的人物与场景。")
        leftover = [i + 1 for i, ref in enumerate(refs) if ref["role"] == "reference"]
        if leftover:
            lines.append(
                "• 其他参考：" + "、".join(f"图{i}" for i in leftover) + " 仅作为补充信息，不要整图照搬。"
            )
        if style["zh"]:
            lines.append(f"• 风格：{style['zh']}。")
        if extra:
            lines.append(f"• 画面要求：{extra}")
        if payload.get("quality", True):
            lines.append(QUALITY_LINES["zh"])
    else:
        if refs:
            header = ", ".join(
                f"image {i + 1} = {_label(ref['role'], 'en')}" for i, ref in enumerate(refs)
            )
            lines.append(f"Reference mapping: {header}.")

        def first_en(role: str) -> int:
            for index, ref in enumerate(refs):
                if ref["role"] == role:
                    return index + 1
            return 0

        character_index = first_en("character")
        costume_index = first_en("costume")
        pose_index = first_en("pose")
        style_index = first_en("style")

        if character_index:
            lines.append(
                f"- Character: use the person in image {character_index}; keep face shape, features, hairstyle, hair color and overall presence consistent."
            )
        if subject:
            lines.append(f"- Character notes: {subject}.")
        if costume_index:
            lines.append(
                f"- Costume: dress the same person in the full outfit and accessories from image {costume_index}; keep cut, colors, materials and wearing style; do not copy its backdrop, display layout or model."
            )
        if pose_index:
            lines.append(
                f"- Pose: follow the body posture, weight distribution, camera angle and framing of image {pose_index}; take only the pose, not its appearance or clothes."
            )
        if style_index:
            lines.append(
                f"- Style: borrow the look, palette and lighting of image {style_index}; do not copy its subject or scene."
            )
        leftover = [i + 1 for i, ref in enumerate(refs) if ref["role"] == "reference"]
        if leftover:
            lines.append(
                "- Extra references: " + ", ".join(f"image {i}" for i in leftover) + " are supporting context only; do not copy them wholesale."
            )
        if style["en"]:
            lines.append(f"- Style: {style['en']}.")
        if extra:
            lines.append(f"- Scene: {extra}")
        if payload.get("quality", True):
            lines.append(QUALITY_LINES["en"])

    for index, ref in enumerate(refs):
        mapping.append({"index": index + 1, "role": ref["role"], "title": ref.get("title", "")})

    return {
        "prompt": "\n".join(line for line in lines if line.strip()),
        "negative": str(payload.get("negative") or DEFAULT_NEGATIVE),
        "refs": mapping,
        "style": style["id"],
    }


def style_catalog() -> list[dict[str, Any]]:
    return STYLE_PRESETS
