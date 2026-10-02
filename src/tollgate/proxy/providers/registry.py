"""Adapter registry + local-server presets (prefill base URL; no key required)."""

from __future__ import annotations

from .anthropic import AnthropicAdapter
from .base import ProviderAdapter
from .openai import LocalAdapter, OpenAIAdapter, OpenAICompatAdapter

_ADAPTERS: dict[str, ProviderAdapter] = {
    "anthropic": AnthropicAdapter(),
    "openai": OpenAIAdapter(),
    "openai-compatible": OpenAICompatAdapter(),
    "local": LocalAdapter(),
}

PROVIDER_TYPES = list(_ADAPTERS)


def get_adapter(provider_type: str) -> ProviderAdapter:
    adapter = _ADAPTERS.get(provider_type)
    if adapter is None:
        raise ValueError(f"unknown provider type: {provider_type}")
    return adapter


def error_payload_for_path(path: str, status: int, message: str, reason: str) -> dict:
    """Shape Tollgate-generated errors like the family the client is calling,
    so existing SDKs parse them correctly."""
    family = "anthropic" if path.startswith("/v1/messages") else "openai"
    return _ADAPTERS[family].error_payload(status, message, reason)


# Local presets: all speak the OpenAI wire format at these default endpoints.
LOCAL_PRESETS: dict[str, dict] = {
    "ollama": {"type": "local", "base_url": "http://localhost:11434/v1"},
    "mlx": {"type": "local", "base_url": "http://localhost:8080/v1"},
    "lmstudio": {"type": "local", "base_url": "http://localhost:1234/v1"},
    "llamacpp": {"type": "local", "base_url": "http://localhost:8081/v1"},
    "vllm": {"type": "local", "base_url": "http://localhost:8000/v1"},
}

# Curated cloud presets (key still required).
CLOUD_PRESETS: dict[str, dict] = {
    "anthropic": {"type": "anthropic", "base_url": "https://api.anthropic.com"},
    "openai": {"type": "openai", "base_url": "https://api.openai.com/v1"},
    "openrouter": {
        "type": "openai-compatible",
        "base_url": "https://openrouter.ai/api/v1",
    },
    "groq": {"type": "openai-compatible", "base_url": "https://api.groq.com/openai/v1"},
}
