"""Multi-level classification for the reference library.

The upstream gallery this app indexes already carries a two-level taxonomy
(pose framing → pose class → camera angle, costume season → garment type →
colour/item, portrait zone → hair length → hairstyle).  The first version of
the importer flattened all of that into a single ``category`` string, which is
exactly why browsing felt coarse: thousands of poses ended up in four buckets.

Everything here is pure: one source record in, one category path plus facet
rows out.  :mod:`app.core.library` persists the result.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from typing import Any, Iterable, Mapping, Sequence

#: Bumped whenever the rules change; ``ensure_taxonomy`` rebuilds older rows.
TAXONOMY_VERSION = "7"

KIND_LABEL = {
    "pose": "姿势",
    "costume": "服装",
    "portrait": "人像",
    "work": "作品",
    "custom": "素材",
    "upload": "上传",
    "other": "其他",
}

#: (field, level) per kind.  Level 1 is the top category, level 2 the sub
#: category shown on cards, level 3+ are optional facets (angle, colour, ...).
FIELDS: dict[str, tuple[tuple[str, int], ...]] = {
    "pose": (("构图", 1), ("姿势分类", 2), ("角度", 3)),
    "costume": (("风格", 1), ("主类", 2), ("品类", 3), ("颜色", 3), ("单品", 3), ("视角", 3)),
    "portrait": (("分区", 1), ("发长", 2), ("发型", 3)),
}
GENERIC_FIELDS: tuple[tuple[str, int], ...] = (("目录", 1), ("目录", 2))

COSTUME_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("连衣裙", ("连衣裙",)),
    ("半身裙", ("半身裙", "裙裤")),
    ("裤装", ("长裤", "短裤", "牛仔裤")),
    ("内衣", ("内衣", "睡衣", "家居服", "文胸", "内裤", "胸衣", "束腰")),
    ("泳装", ("泳衣", "泳装", "比基尼")),
    ("外套", ("大衣", "夹克", "开衫", "风衣", "西装")),
    ("鞋履", ("靴", "凉鞋", "高跟鞋", "运动鞋", "乐福鞋", "单鞋", "拖鞋")),
    ("袜类", ("袜",)),
    ("包袋", ("包",)),
    (
        "配饰",
        ("项链", "颈链", "腰带", "礼帽", "发箍", "手套", "墨镜", "丝巾", "围巾", "冷帽", "贝雷帽", "帽子", "配饰"),
    ),
    (
        "上装",
        ("针织衫", "针织", "衬衫", "女衫", "罩衫", "毛衣", "马甲", "卫衣", "吊带", "背心", "T恤"),
    ),
)

COLOR_ORDER: tuple[str, ...] = (
    "黑色", "白色", "象牙白", "奶油色", "米色", "灰色", "棕色", "卡其色",
    "红色", "酒红色", "粉色", "橙色", "黄色", "金色", "银色",
    "蓝色", "藏青色", "绿色", "薄荷绿", "橄榄绿", "紫色", "薰衣草紫",
)
COLORS = frozenset(COLOR_ORDER)

#: Content flags used by the "显示 NSFW 素材" preference (off by default).
NSFW_POSE_CLASSES = frozenset({"性感・大胆系", "挤胸・强调事业线系"})
NSFW_POSE_SERIES = frozenset({"双人缠绵"})
NSFW_COSTUME_STYLES = frozenset({"内衣・睡衣", "性感穿搭", "泳装・度假"})

_SPLIT = re.compile(r"[\\/・、,，;；\s]+")


@dataclass(slots=True)
class Classification:
    """Category path and facet rows for one library item."""

    category: str
    category_path: str
    facets: list[tuple[str, str, int]] = dc_field(default_factory=list)
    tags: str = ""
    search_text: str = ""
    nsfw: bool = False


def clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " ".join(part for part in (clean(item) for item in value) if part)
    return re.sub(r"\s+", " ", str(value)).strip()


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        value = clean(value)
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _join(values: Iterable[str]) -> str:
    return " ".join(_unique(values))


def _path(*parts: str) -> str:
    return " / ".join(part for part in parts if part)


def _finalize(
    *,
    category: str,
    category_path: str,
    facets: Iterable[tuple[str, str, int]],
    search_parts: Iterable[str],
    tags: Iterable[str],
    nsfw: bool = False,
) -> Classification:
    unique: list[tuple[str, str, int]] = []
    seen: set[tuple[str, str]] = set()
    for name, value, level in facets:
        value = clean(value)
        if not value or (name, value) in seen:
            continue
        seen.add((name, value))
        unique.append((name, value, level))

    category = clean(category) or "未分类"
    blob = " ".join([*(clean(part) for part in search_parts), *(value for _, value, _ in unique)])
    return Classification(
        category=category,
        category_path=clean(category_path) or category,
        facets=unique,
        tags=_join(tags),
        search_text=re.sub(r"\s+", " ", blob).strip().lower(),
        nsfw=bool(nsfw),
    )


# ── pose ──────────────────────────────────────────────────────────────────


def classify_pose(entry: Mapping[str, Any]) -> Classification:
    series = clean(entry.get("体系") or entry.get("构图"))
    sub = clean(entry.get("分类") or entry.get("姿势分类"))
    angle = clean(entry.get("角度"))
    name = clean(entry.get("姿势名称") or entry.get("名称"))
    code = clean(entry.get("姿势编号"))
    ident = clean(entry.get("id"))

    return _finalize(
        category=sub or series,
        category_path=_path(series, sub),
        facets=(("构图", series, 1), ("姿势分类", sub, 2), ("角度", angle, 3)),
        search_parts=(name, series, sub, angle, code, ident),
        tags=("姿势", series, sub, angle),
        nsfw=("性感" in series or series in NSFW_POSE_SERIES or sub in NSFW_POSE_CLASSES),
    )


# ── costume ───────────────────────────────────────────────────────────────


def _piece_type(piece: str) -> str:
    for label, keys in COSTUME_RULES:
        if any(key in piece for key in keys):
            return label
    return ""


def garment_types(name: str, labels: Sequence[str] = ()) -> list[str]:
    """Ordered garment types, primary piece first."""

    pieces = [piece for piece in _SPLIT.split(name) if piece]
    found: list[str] = []
    for piece in pieces:
        label = _piece_type(piece)
        if label and label not in found:
            found.append(label)
    if found:
        return found
    for label, keys in COSTUME_RULES:
        if any(key in labels for key in keys) and label not in found:
            found.append(label)
    return found


def _colors(labels: Sequence[str], name: str) -> list[str]:
    present = [color for color in COLOR_ORDER if color in labels]
    if present:
        return present
    return [color for color in COLOR_ORDER if color in name]


def classify_costume(entry: Mapping[str, Any]) -> Classification:
    style = clean(entry.get("分类") or entry.get("风格"))
    name = clean(entry.get("服装名称") or entry.get("名称"))
    labels = [clean(label) for label in (entry.get("标签") or []) if clean(label)]
    keywords = clean(entry.get("关键词"))
    ident = clean(entry.get("id"))
    view = clean(entry.get("视角") or entry.get("view_label") or entry.get("selectedView"))

    types = garment_types(name, labels)
    colors = _colors(labels, name)
    primary = types[0] if types else ""
    facets: list[tuple[str, str, int]] = [("风格", style, 1), ("主类", primary, 2)]
    facets += [("品类", item, 3) for item in types]
    facets += [("颜色", color, 3) for color in colors]
    facets += [("单品", label, 3) for label in labels]
    if view:
        facets.append(("视角", view, 3))

    category = primary or style
    return _finalize(
        category=category,
        category_path=_path(style, primary) if primary else style,
        facets=facets,
        search_parts=(name, style, *types, *labels, *colors, keywords, ident, view),
        tags=("服装", style, *types, *colors, view),
        nsfw=style in NSFW_COSTUME_STYLES,
    )


# ── portrait ──────────────────────────────────────────────────────────────


def classify_portrait(entry: Mapping[str, Any]) -> Classification:
    zone = clean(entry.get("分区"))
    length = clean(entry.get("发长"))
    style = clean(entry.get("发型名称"))
    title = clean(entry.get("标题") or entry.get("名称"))
    ident = clean(entry.get("id"))

    return _finalize(
        category=length or zone,
        category_path=_path(zone, length),
        facets=(("分区", zone, 1), ("发长", length, 2), ("发型", style, 3)),
        search_parts=(title, zone, length, style, ident),
        tags=("人像", zone, length, style),
    )


# ── folders / uploads ─────────────────────────────────────────────────────


def classify_folder(relative: str, title: str = "") -> Classification:
    """Generic folder import: top folder is the group, last folder the sub-group."""

    parts = [part for part in _SPLIT.split(relative.replace("\\", "/")) if part]
    directories = parts[:-1] if len(parts) > 1 else []
    top = directories[0] if directories else "根目录"
    leaf = directories[-1] if directories else "根目录"
    facets: list[tuple[str, str, int]] = [("目录", top, 1)]
    if len(directories) > 1:
        facets.append(("目录", leaf, 2))
    return _finalize(
        category=leaf,
        category_path=" / ".join(directories) if directories else "根目录",
        facets=facets,
        search_parts=(title, relative, *directories),
        tags=("素材", *directories[:2]),
    )


def classify_upload(title: str = "") -> Classification:
    return _finalize(
        category="上传",
        category_path="上传",
        facets=(("目录", "上传", 1),),
        search_parts=(title, "上传"),
        tags=("上传",),
    )


def classify_work(title: str = "") -> Classification:
    """A generated work that the user saved back into the reference library."""

    return _finalize(
        category="我的作品",
        category_path="我的作品",
        facets=(("目录", "我的作品", 1),),
        search_parts=(title, "作品"),
        tags=("作品",),
    )


# ── dispatch ──────────────────────────────────────────────────────────────


def classify_entry(kind: str, entry: Mapping[str, Any]) -> Classification:
    if kind == "pose":
        return classify_pose(entry)
    if kind == "costume":
        return classify_costume(entry)
    if kind == "portrait":
        return classify_portrait(entry)
    return classify_folder(clean(entry.get("id")) or clean(entry.get("原图")), clean(entry.get("标题")))


def field_names(kind: str) -> tuple[str, ...]:
    return tuple(name for name, _ in FIELDS.get(kind, GENERIC_FIELDS))


def query_tokens(query: str) -> list[str]:
    return [token.lower() for token in _SPLIT.split(clean(query)) if token]
