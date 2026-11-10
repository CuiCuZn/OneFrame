"""Pydantic request/response schemas for the local API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class KeyIn(BaseModel):
    label: str = Field(default="", max_length=80)
    secret: str = Field(min_length=1, max_length=4000)
    enabled: bool = True


class ChannelIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    protocol: str = Field(min_length=1, max_length=40)
    base_url: str = Field(default="", max_length=500)
    headers: dict[str, str] = Field(default_factory=dict)
    note: str = Field(default="", max_length=500)
    enabled: bool = True
    keys: list[KeyIn] = Field(default_factory=list)

    @field_validator("base_url")
    @classmethod
    def clean_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("服务地址必须以 http:// 或 https:// 开头")
        return value


class RouteIn(BaseModel):
    """Deprecated: v2 binds a model directly to one channel."""

    channel_id: str = ""
    upstream_model: str = ""
    priority: int = 100
    weight: int = 100
    enabled: bool = True
    overrides: dict[str, Any] = Field(default_factory=dict)


class PriceIn(BaseModel):
    mode: Literal["unconfigured", "per_image", "per_request", "per_second"] = "unconfigured"
    amount: float = Field(default=0, ge=0, le=100000)
    currency: str = Field(default="CNY", max_length=8)


class CapsIn(BaseModel):
    max_refs: int = Field(default=0, ge=0, le=16)
    max_count: int = Field(default=1, ge=1, le=16)
    features: list[str] = Field(default_factory=list)
    sizes: list[str] = Field(default_factory=list)
    aspects: list[str] = Field(default_factory=list)


class ModelIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    modality: Literal["image", "video"]
    channel_id: str = Field(min_length=1, max_length=64)
    upstream_model: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=500)
    enabled: bool = True
    caps: CapsIn = Field(default_factory=CapsIn)
    params: dict[str, list[str]] = Field(default_factory=dict)
    price: PriceIn = Field(default_factory=PriceIn)
    overrides: dict[str, Any] = Field(default_factory=dict)


class RefIn(BaseModel):
    asset_id: str | None = None
    library_id: str | None = None
    role: str = "reference"
    name: str = ""
    variant: Literal["base", "depth"] = "base"


class GenerateIn(BaseModel):
    model_id: str
    prompt: str = Field(default="", max_length=8000)
    negative: str = Field(default="", max_length=4000)
    count: int = Field(default=1, ge=1, le=16)
    params: dict[str, Any] = Field(default_factory=dict)
    refs: list[RefIn] = Field(default_factory=list, max_length=16)
    style: str = Field(default="none", max_length=40)
    source: str = Field(default="studio", max_length=40)
    tool: Literal["", "extract_costume", "refine", "inpaint", "character"] = ""
    options: dict[str, Any] = Field(default_factory=dict)
    mask: str | None = Field(default=None, max_length=12_000_000)
    matrix_id: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def require_prompt_unless_tool(self):
        if not self.tool and not self.prompt.strip():
            raise ValueError("请先填写提示词")
        return self


class CompileIn(BaseModel):
    refs: list[dict[str, Any]] = Field(default_factory=list)
    style: str = "none"
    extra: str = ""
    subject: str = ""
    language: str = "zh"
    quality: bool = True
    negative: str = ""


class AssetPatch(BaseModel):
    favorite: bool | None = None
    tags: str | None = Field(default=None, max_length=500)


class SplitIn(BaseModel):
    rows: int = Field(default=2, ge=1, le=4)
    columns: int = Field(default=2, ge=1, le=4)
    cells: list[int] | None = Field(default=None, max_length=16)


class UpscaleIn(BaseModel):
    factor: Literal[2, 4] = 2


class PromptIn(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    category: Literal["quality", "camera", "lighting", "style", "custom"] = "custom"
    text: str = Field(min_length=1, max_length=4000)
    negative: str = Field(default="", max_length=4000)
    tags: str = Field(default="", max_length=200)
    favorite: bool = False


class EnhanceIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    negative: str = Field(default="", max_length=4000)
    style: str = Field(default="none", max_length=40)
    modality: Literal["image", "video"] = "image"
    has_refs: bool = False
    language: Literal["zh", "en"] = "zh"


class LibraryPatch(BaseModel):
    favorite: bool | None = None
    tags: str | None = Field(default=None, max_length=500)


class ImportIn(BaseModel):
    mode: Literal["folder", "pose_gallery"] = "folder"
    path: str
    kind: str = "other"


class SettingsIn(BaseModel):
    values: dict[str, str]
