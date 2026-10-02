"""Live price refresh from LiteLLM / OpenRouter (fetched, diffed, reviewed)."""

from __future__ import annotations

import httpx

from .bands import PriceChange, apply_changes, diff_against
from .loader import parse_litellm_map, parse_openrouter


async def fetch_litellm(http: httpx.AsyncClient, url: str) -> dict:
    resp = await http.get(url)
    resp.raise_for_status()
    return parse_litellm_map(resp.json())


async def fetch_openrouter(http: httpx.AsyncClient, url: str) -> dict:
    resp = await http.get(url)
    resp.raise_for_status()
    return parse_openrouter(resp.json())


async def refresh(
    session, http: httpx.AsyncClient, url: str, source: str = "litellm-live"
) -> list[PriceChange]:
    """Fetch → diff → apply. Returns the applied changes for the audit log."""
    if "openrouter" in url:
        incoming = await fetch_openrouter(http, url)
    else:
        incoming = await fetch_litellm(http, url)
    changes = await diff_against(session, incoming)
    await apply_changes(session, changes, source)
    return changes
