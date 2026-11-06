"""Protocol registry: adapters self-describe so the UI can build editors."""

from __future__ import annotations

from typing import Any

from .base import Adapter, GenRequest, ProviderContext, RefImage
from .gemini import GeminiImageAdapter, GeminiVideoAdapter
from .generic import DEFAULT_CONFIG, GenericAdapter
from .mock import MockAdapter
from .openai_images import OpenAIImagesAdapter
from .openai_video import OpenAIVideoAdapter

ADAPTERS: dict[str, Adapter] = {
    adapter.protocol: adapter
    for adapter in (
        OpenAIImagesAdapter(),
        OpenAIVideoAdapter(),
        GeminiImageAdapter(),
        GeminiVideoAdapter(),
        GenericAdapter(),
        MockAdapter(),
    )
}

PROTOCOL_DOCS: dict[str, dict[str, Any]] = {
    "openai_image": {
        "base_url": "https://api.openai.com/v1",
        "key_hint": "sk-...",
        "docs": "https://platform.openai.com/docs/api-reference/images",
    },
    "openai_video": {
        "base_url": "https://api.openai.com/v1",
        "key_hint": "sk-...",
        "docs": "https://platform.openai.com/docs/api-reference/videos",
    },
    "gemini_image": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "key_hint": "AIza...",
        "docs": "https://ai.google.dev/gemini-api/docs/image-generation",
    },
    "gemini_video": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "key_hint": "AIza...",
        "docs": "https://ai.google.dev/gemini-api/docs/video",
    },
    "generic": {
        "base_url": "https://your-gateway.example.com",
        "key_hint": "任意 token",
        "template": DEFAULT_CONFIG,
    },
    "mock": {"base_url": "", "key_hint": ""},
}


def get_adapter(protocol: str) -> Adapter:
    adapter = ADAPTERS.get(protocol)
    if not adapter:
        raise KeyError(protocol)
    return adapter


def catalog() -> list[dict[str, Any]]:
    items = []
    for protocol, adapter in ADAPTERS.items():
        items.append(
            {
                "id": protocol,
                "label": adapter.label,
                "modalities": sorted(adapter.modalities),
                "supports_reference": adapter.supports_reference,
                "supports_video": adapter.supports_video,
                "params": list(adapter.param_keys),
                "about": adapter.about,
                **PROTOCOL_DOCS.get(protocol, {}),
            }
        )
    return items


__all__ = [
    "ADAPTERS",
    "Adapter",
    "GenRequest",
    "ProviderContext",
    "RefImage",
    "catalog",
    "get_adapter",
]
