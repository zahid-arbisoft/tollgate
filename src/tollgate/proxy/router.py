"""Route resolution: alias → provider chain, or direct provider by family.

An alias maps an incoming model name to (provider, upstream_model) plus an
ordered fallback list. Without a matching alias, requests go to the first
enabled provider of the family the endpoint implies (anthropic endpoints →
anthropic providers; openai endpoints → openai/openai-compatible/local).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..store.models import Alias, Provider, VirtualKey


@dataclass
class RouteHop:
    provider: Provider
    upstream_model: str
    via_alias: str | None = None


FAMILY_FOR_PATH = {
    "/v1/messages": "anthropic",
    "/v1/messages/count_tokens": "anthropic",
    "/v1/chat/completions": "openai",
    "/v1/completions": "openai",
    "/v1/embeddings": "openai",
    "/v1/models": "openai",
}


class RouteError(Exception):
    def __init__(self, status_code: int, reason: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.reason = reason
        self.message = message


def _family_providers(providers: list[Provider], family: str) -> list[Provider]:
    if family == "anthropic":
        ok = {"anthropic"}
    else:
        ok = {"openai", "openai-compatible", "local"}
    return [p for p in providers if p.enabled and p.type in ok]


async def resolve_routes(
    session: AsyncSession,
    endpoint_path: str,
    requested_model: str | None,
    key: VirtualKey | None,
) -> tuple[list[RouteHop], str | None]:
    """Returns (ordered hops, alias_used). Raises RouteError when unroutable."""
    providers = list((await session.execute(select(Provider))).scalars())
    enabled = [p for p in providers if p.enabled]
    alias: Alias | None = None
    if requested_model:
        alias = (
            await session.execute(select(Alias).where(Alias.alias_name == requested_model))
        ).scalar_one_or_none()
        if alias is not None and not alias.enabled:
            alias = None

    hops: list[RouteHop] = []
    if alias is not None:
        primary = next((p for p in enabled if p.id == alias.provider_id), None)
        if primary is not None:
            hops.append(RouteHop(primary, alias.upstream_model, alias.alias_name))
        for fb in alias.fallbacks or []:
            pid = fb.get("provider_id")
            model = fb.get("upstream_model") or alias.upstream_model
            p = next((x for x in enabled if x.id == pid), None)
            if p is not None:
                hops.append(RouteHop(p, model, alias.alias_name))
    elif requested_model:
        # Direct: first enabled provider of this endpoint's family carries the
        # model name upstream unchanged.
        family = FAMILY_FOR_PATH.get(endpoint_path, "openai")
        for p in _family_providers(providers, family):
            hops.append(RouteHop(p, requested_model))
    else:
        family = FAMILY_FOR_PATH.get(endpoint_path, "openai")
        for p in _family_providers(providers, family):
            hops.append(RouteHop(p, ""))

    if not hops:
        raise RouteError(503, "no_provider", "No enabled provider can serve this request.")

    # Key allowlists (empty/None = allow all).
    if key is not None:
        allowed_p = key.allowed_providers or []
        allowed_m = key.allowed_models_aliases or []
        if allowed_p:
            hops = [h for h in hops if h.provider.name in allowed_p]
        if allowed_m:
            if requested_model and requested_model in allowed_m:
                pass  # requested model explicitly allowed — all hops fine
            elif alias is not None and alias.alias_name in allowed_m:
                hops = [h for h in hops if h.via_alias == alias.alias_name]
            else:
                raise RouteError(
                    403,
                    "model_not_allowed",
                    f"Model '{requested_model}' is not allowed for this key.",
                )
        if not hops:
            raise RouteError(403, "provider_not_allowed", "No allowed provider for this key.")

    return hops, (alias.alias_name if alias else None)
