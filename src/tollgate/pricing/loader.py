"""Price-map loading & normalization.

Sources (plan §6): the vendored LiteLLM community cost map (bundled with the
app, refreshed on updates), a live LiteLLM fetch, OpenRouter as cross-check,
and manual entries from the UI (which always win).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

VENDORED_PATH = Path(__file__).parent / "data" / "model_prices_and_context_window.json"


@dataclass(frozen=True)
class PriceEntry:
    model: str
    price_in: float = 0.0
    price_out: float = 0.0
    price_cache_read: float = 0.0
    price_cache_write: float = 0.0
    context_window: int | None = None


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _i(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None  # some entries carry description strings in these fields


def parse_litellm_map(data: dict) -> dict[str, PriceEntry]:
    """LiteLLM `model_prices_and_context_window.json` → normalized entries."""
    out: dict[str, PriceEntry] = {}
    for model, info in data.items():
        if not isinstance(info, dict):
            continue  # meta keys
        has_cost = any(
            info.get(k) is not None
            for k in (
                "input_cost_per_token",
                "output_cost_per_token",
                "cache_read_input_token_cost",
                "cache_creation_input_token_cost",
            )
        )
        cw = info.get("max_input_tokens") or info.get("max_tokens")
        if not has_cost and not cw:
            continue
        out[model] = PriceEntry(
            model=model,
            price_in=_f(info.get("input_cost_per_token")),
            price_out=_f(info.get("output_cost_per_token")),
            price_cache_read=_f(info.get("cache_read_input_token_cost")),
            price_cache_write=_f(info.get("cache_creation_input_token_cost")),
            context_window=_i(cw),
        )
    return out


def parse_openrouter(data: dict) -> dict[str, PriceEntry]:
    """OpenRouter /api/v1/models — pricing is per-1M tokens (convert)."""
    out: dict[str, PriceEntry] = {}

    def per_token(pricing: dict, key: str) -> float:
        v = pricing.get(key)
        return _f(v) / 1e6 if v is not None else 0.0

    for m in data.get("data", []):
        pricing = m.get("pricing") or {}
        out[m["id"]] = PriceEntry(
            model=m["id"],
            price_in=per_token(pricing, "prompt"),
            price_out=per_token(pricing, "completion"),
            price_cache_read=per_token(pricing, "cache_read"),
            price_cache_write=per_token(pricing, "cache_write"),
            context_window=m.get("context_length"),
        )
    return out


def load_vendored() -> dict[str, PriceEntry]:
    return parse_litellm_map(json.loads(VENDORED_PATH.read_bytes()))
