"""Proxy endpoints — what client projects call (base URL is Tollgate's).

Anthropic-native: POST /v1/messages, POST /v1/messages/count_tokens
OpenAI: POST /v1/chat/completions, POST /v1/completions, GET /v1/models
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ..auth.dependency import authenticate
from ..store.models import VirtualKey
from .pipeline import proxy_request

router = APIRouter(tags=["proxy"])


@router.post("/v1/messages")
async def messages(request: Request, key: VirtualKey = Depends(authenticate)):
    return await proxy_request(request, "/v1/messages", key)


@router.post("/v1/messages/count_tokens")
async def count_tokens(request: Request, key: VirtualKey = Depends(authenticate)):
    return await proxy_request(request, "/v1/messages/count_tokens", key)


@router.post("/v1/chat/completions")
async def chat_completions(request: Request, key: VirtualKey = Depends(authenticate)):
    return await proxy_request(request, "/v1/chat/completions", key)


@router.post("/v1/completions")
async def completions(request: Request, key: VirtualKey = Depends(authenticate)):
    return await proxy_request(request, "/v1/completions", key)


@router.get("/v1/models")
async def models(request: Request, key: VirtualKey = Depends(authenticate)):
    """List what this key may use: configured aliases (curated view of models)."""
    from sqlalchemy import select

    from ..store.models import Alias, Provider

    allowed = key.allowed_models_aliases or []
    async with request.app.state.session_factory() as session:
        aliases = list((await session.execute(select(Alias))).scalars())
        providers = {p.id: p for p in (await session.execute(select(Provider))).scalars()}

    data = []
    for a in aliases:
        if not a.enabled:
            continue
        if allowed and a.alias_name not in allowed:
            continue
        owner = providers.get(a.provider_id)
        data.append(
            {
                "id": a.alias_name,
                "object": "model",
                "owned_by": owner.name if owner else "tollgate",
            }
        )
    return JSONResponse({"object": "list", "data": data})
