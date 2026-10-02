"""Admin REST API (/admin/*) — bearer admin token (plan §8).

Everything the dashboard and CLI drive: keys, limits, providers, aliases,
prices (bands + refresh w/ diff review), logs + export, stats, SSE live tail,
settings, backups.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import shutil
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.service import KeyService
from ..config import Settings
from ..pricing.bands import (
    apply_changes,
    current_band,
    diff_against,
    set_manual,
)
from ..pricing.loader import PriceEntry, parse_litellm_map, parse_openrouter
from ..security.hashing import sha256_hex
from ..store.engine import get_session
from ..store.models import (
    Alias,
    LimitRule,
    ModelPrice,
    Provider,
    RequestLog,
    Setting,
    VirtualKey,
)
from ..sync.events import emit
from ..sync.serialize import (
    alias_payload,
    key_payload,
    limit_payload,
    price_payload,
    provider_payload,
    setting_payload,
)
from . import stats as stats_mod

router = APIRouter(tags=["admin"])


# ---------------------------------------------------------------- auth


async def require_admin(request: Request) -> None:
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not token or sha256_hex(token) != request.app.state.admin_token_sha256:
        raise HTTPException(status_code=401, detail="admin token required")


# ---------------------------------------------------------------- schemas


class KeyCreate(BaseModel):
    name: str = ""
    project: str | None = None
    notes: str | None = None
    expires_in_days: int | None = None
    allowed_providers: list[str] | None = None
    allowed_models_aliases: list[str] | None = None
    store_plaintext: bool = False


class KeyUpdate(BaseModel):
    name: str | None = None
    project: str | None = None
    notes: str | None = None
    allowed_providers: list[str] | None = None
    allowed_models_aliases: list[str] | None = None


class KeyExtend(BaseModel):
    days: int


class LimitIn(BaseModel):
    key_id: str | None = None
    metric: str
    window: str
    value: float
    action: str = "reject"
    auto_block: bool = False


class LimitUpdate(BaseModel):
    key_id: str | None = None
    metric: str | None = None
    window: str | None = None
    value: float | None = None
    action: str | None = None
    auto_block: bool | None = None


class ProviderIn(BaseModel):
    type: str
    name: str
    base_url: str
    api_key: str | None = None  # write-only; stored in the secret store
    enabled: bool = True
    timeout_s: float = 120.0
    retries: int = 0
    notes: str | None = None


class ProviderUpdate(BaseModel):
    type: str | None = None
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    enabled: bool | None = None
    timeout_s: float | None = None
    retries: int | None = None
    notes: str | None = None


class AliasIn(BaseModel):
    alias_name: str
    provider_id: int
    upstream_model: str
    fallbacks: list[dict] = Field(default_factory=list)
    enabled: bool = True


class AliasUpdate(BaseModel):
    alias_name: str | None = None
    provider_id: int | None = None
    upstream_model: str | None = None
    fallbacks: list[dict] | None = None
    enabled: bool | None = None


class ManualPriceIn(BaseModel):
    model: str
    price_in: float = 0.0
    price_out: float = 0.0
    price_cache_read: float = 0.0
    price_cache_write: float = 0.0
    context_window: int | None = None


class RefreshApply(BaseModel):
    accept: Any = "all"  # "all" or list of model names


class SettingsIn(BaseModel):
    retention_days: int | None = None
    log_bodies: bool | None = None
    webhook_url: str | None = None


# ---------------------------------------------------------------- helpers


def key_out(k: VirtualKey) -> dict:
    return {
        "id": k.id,
        "prefix": k.prefix,
        "name": k.name,
        "project": k.project,
        "status": k.status,
        "blocked_reason": k.blocked_reason,
        "created_at": k.created_at.isoformat(),
        "expires_at": k.expires_at.isoformat() if k.expires_at else None,
        "rotated_from": k.rotated_from,
        "notes": k.notes,
        "allowed_providers": k.allowed_providers,
        "allowed_models_aliases": k.allowed_models_aliases,
        "has_stored_plaintext": bool(k.secret_handle),
    }


def log_out(row: RequestLog, keys_by_id: dict[str, VirtualKey] | None = None) -> dict:
    d = {
        "id": row.id,
        "instance_id": row.instance_id,
        "ts": row.ts.isoformat(),
        "key_id": row.key_id,
        "key": None,
        "project": None,
        "provider": row.provider,
        "model": row.model,
        "alias_used": row.alias_used,
        "endpoint": row.endpoint,
        "status_code": row.status_code,
        "latency_total_ms": row.latency_total_ms,
        "upstream_ms": row.upstream_ms,
        "tokens_in": row.tokens_in,
        "tokens_out": row.tokens_out,
        "cache_read": row.cache_read,
        "cache_write": row.cache_write,
        "cost_usd": row.cost_usd,
        "price_band_id": row.price_band_id,
        "is_stream": row.is_stream,
        "estimated": row.estimated,
        "error": row.error,
        "request_bytes": row.request_bytes,
        "response_bytes": row.response_bytes,
        "client_ip": row.client_ip,
        "fallback_hops": row.fallback_hops,
    }
    if keys_by_id and row.key_id in keys_by_id:
        k = keys_by_id[row.key_id]
        d["key"] = k.prefix
        d["project"] = k.project
    return d


def provider_out(p: Provider, key_present: bool | None = None) -> dict:
    # key_present: whether the LOCAL secret store actually holds the key.
    # None (no store access) falls back to the handle for backwards compat.
    return {
        "id": p.id,
        "type": p.type,
        "name": p.name,
        "base_url": p.base_url,
        "has_key": key_present if key_present is not None else bool(p.secret_handle),
        "enabled": p.enabled,
        "timeout_s": p.timeout_s,
        "retries": p.retries,
        "notes": p.notes,
        "created_at": p.created_at.isoformat(),
    }


def _svc(request: Request) -> KeyService:
    return request.app.state.key_service


async def _emit_key(app, key, op: str = "upsert") -> None:
    """Config event for key lifecycle changes that go through KeyService
    (which commits in its own session)."""
    from ..store.models import VirtualKey as VK

    async with app.state.session_factory() as s:
        row = key if isinstance(key, VK) else await s.get(VK, key)
        await emit(app, s, "key", row.id, op, key_payload(row) if op == "upsert" else None)
        await s.commit()


# ---------------------------------------------------------------- keys


@router.get("/keys")
async def list_keys(_: None = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(VirtualKey))).scalars().all()
    return [key_out(k) for k in sorted(rows, key=lambda r: r.created_at, reverse=True)]


@router.post("/keys", status_code=201)
async def create_key(
    body: KeyCreate,
    request: Request,
    _: None = Depends(require_admin),
):
    key, plaintext = await _svc(request).create(
        name=body.name,
        project=body.project,
        notes=body.notes,
        expires_in_days=body.expires_in_days,
        allowed_providers=body.allowed_providers,
        allowed_models_aliases=body.allowed_models_aliases,
        store_plaintext=body.store_plaintext,
    )
    return {
        **key_out(key),
        "plaintext": plaintext,
    }  # shown exactly once (event emitted by KeyService)


@router.get("/keys/{key_id}")
async def get_key(
    key_id: str,
    _: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    key = await session.get(VirtualKey, key_id)
    if key is None:
        raise HTTPException(404)
    return key_out(key)


@router.patch("/keys/{key_id}")
async def update_key(
    key_id: str,
    body: KeyUpdate,
    request: Request,
    _: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    key = await session.get(VirtualKey, key_id)
    if key is None:
        raise HTTPException(404)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(key, field, value)
    await session.commit()
    await emit(request.app, session, "key", key.id, payload=key_payload(key))
    await session.commit()
    return key_out(key)


@router.post("/keys/{key_id}/rotate")
async def rotate_key(key_id: str, request: Request, _: None = Depends(require_admin)):
    try:
        new_key, plaintext = await _svc(request).rotate(key_id)
    except KeyError:
        raise HTTPException(404) from None
    await _emit_key(request.app, new_key)
    return {**key_out(new_key), "plaintext": plaintext}


@router.post("/keys/{key_id}/extend")
async def extend_key(
    key_id: str, body: KeyExtend, request: Request, _: None = Depends(require_admin)
):
    key = await _svc(request).extend(key_id, body.days)
    if key is None:
        raise HTTPException(404)
    return key_out(key)


@router.post("/keys/{key_id}/{action}")
async def key_action(key_id: str, action: str, request: Request, _: None = Depends(require_admin)):
    reasons = {
        "disable": None,
        "enable": None,
        "block": "manual block",
        "unblock": None,
    }
    if action not in reasons:
        raise HTTPException(404, f"unknown action {action}")
    status = {"disable": "disabled", "enable": "active", "block": "blocked", "unblock": "active"}[
        action
    ]
    key = await _svc(request).set_status(
        key_id, status, reason=reasons[action] if action == "block" else None
    )
    if key is None:
        raise HTTPException(404)
    return key_out(key)


@router.delete("/keys/{key_id}", status_code=204)
async def delete_key(
    key_id: str,
    request: Request,
    _: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    key = await session.get(VirtualKey, key_id)
    if key is None:
        raise HTTPException(404)
    if key.secret_handle:
        request.app.state.secrets.delete(key.secret_handle)
    await emit(request.app, session, "key", key.id, "tombstone")
    await session.delete(key)
    await session.commit()


# ---------------------------------------------------------------- limits


def limit_out(r: LimitRule) -> dict:
    return {
        "id": r.id,
        "key_id": r.key_id,
        "metric": r.metric,
        "window": r.window,
        "value": r.value,
        "action": r.action,
        "auto_block": r.auto_block,
    }


@router.get("/limits")
async def list_limits(
    key_id: str | None = None,
    _: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(LimitRule).where(LimitRule.key_id == key_id) if key_id else select(LimitRule)
    rows = (await session.execute(stmt)).scalars().all()
    return [limit_out(r) for r in rows]


@router.post("/limits", status_code=201)
async def create_limit(
    request: Request,
    body: LimitIn,
    _: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    if body.metric not in stats_mod_limit_metrics():
        raise HTTPException(422, f"metric must be one of {stats_mod_limit_metrics()}")
    if body.window not in ("minute", "hour", "day", "month", "total"):
        raise HTTPException(422, "invalid window")
    rule = LimitRule(**body.model_dump())
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    await emit(request.app, session, "limit", rule.id, payload=limit_payload(rule))
    await session.commit()
    return limit_out(rule)


def stats_mod_limit_metrics():
    from ..limits.enforcer import METRICS

    return METRICS


@router.patch("/limits/{rule_id}")
async def update_limit(
    rule_id: int,
    body: LimitUpdate,
    request: Request,
    _: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    rule = await session.get(LimitRule, rule_id)
    if rule is None:
        raise HTTPException(404)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    await session.commit()
    await emit(request.app, session, "limit", rule.id, payload=limit_payload(rule))
    await session.commit()
    return limit_out(rule)


@router.delete("/limits/{rule_id}", status_code=204)
async def delete_limit(
    request: Request,
    rule_id: int,
    _: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    rule = await session.get(LimitRule, rule_id)
    if rule is None:
        raise HTTPException(404)
    await emit(request.app, session, "limit", rule.id, "tombstone")
    await session.delete(rule)
    await session.commit()


# ---------------------------------------------------------------- providers


@router.get("/providers")
async def list_providers(
    _: None = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    rows = (await session.execute(select(Provider))).scalars().all()
    return [provider_out(p) for p in rows]


@router.get("/providers/presets")
async def provider_presets(_: None = Depends(require_admin)):
    from ..proxy.providers.registry import CLOUD_PRESETS, LOCAL_PRESETS

    return {"local": LOCAL_PRESETS, "cloud": CLOUD_PRESETS}


@router.post("/providers", status_code=201)
async def create_provider(
    body: ProviderIn,
    request: Request,
    _: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    from ..proxy.providers.registry import PROVIDER_TYPES

    if body.type not in PROVIDER_TYPES:
        raise HTTPException(422, f"type must be one of {PROVIDER_TYPES}")
    p = Provider(
        type=body.type,
        name=body.name,
        base_url=body.base_url,
        enabled=body.enabled,
        timeout_s=body.timeout_s,
        retries=body.retries,
        notes=body.notes,
    )
    session.add(p)
    await session.flush()
    if body.api_key:
        p.secret_handle = f"provider:{p.id}"
        request.app.state.secrets.set(p.secret_handle, body.api_key)
    await session.commit()
    await session.refresh(p)
    await emit(request.app, session, "provider", p.id, payload=provider_payload(p))
    await session.commit()
    return provider_out(p)


@router.patch("/providers/{provider_id}")
async def update_provider(
    provider_id: int,
    body: ProviderUpdate,
    request: Request,
    _: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    p = await session.get(Provider, provider_id)
    if p is None:
        raise HTTPException(404)
    for field in ("type", "name", "base_url", "enabled", "timeout_s", "retries", "notes"):
        value = body.model_dump(exclude_unset=True).get(field)
        if value is not None:
            setattr(p, field, value)  # api_key handled below (secrets)
    if body.api_key is not None:
        if body.api_key == "":
            request.app.state.secrets.delete(f"provider:{p.id}")
            p.secret_handle = None
        else:
            p.secret_handle = f"provider:{p.id}"
            request.app.state.secrets.set(p.secret_handle, body.api_key)
    await session.commit()
    await emit(request.app, session, "provider", p.id, payload=provider_payload(p))
    await session.commit()
    return provider_out(p)


@router.delete("/providers/{provider_id}", status_code=204)
async def delete_provider(
    provider_id: int,
    request: Request,
    _: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    p = await session.get(Provider, provider_id)
    if p is None:
        raise HTTPException(404)
    if p.secret_handle:
        request.app.state.secrets.delete(p.secret_handle)
    await emit(request.app, session, "provider", p.id, "tombstone")
    await session.delete(p)
    await session.commit()


@router.post("/providers/{provider_id}/test")
async def test_provider(
    provider_id: int,
    request: Request,
    _: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    import httpx

    from ..proxy.providers.registry import get_adapter

    p = await session.get(Provider, provider_id)
    if p is None:
        raise HTTPException(404)
    adapter = get_adapter(p.type)
    api_key = request.app.state.secrets.get(f"provider:{p.id}") if p.secret_handle else None
    url = p.base_url.rstrip("/") + ("/v1/models" if p.type == "anthropic" else "/models")
    t0 = time.perf_counter()
    try:
        resp = await request.app.state.http.get(
            url, headers=adapter.auth_headers(api_key), timeout=10.0
        )
        ok = resp.status_code < 400
        return {
            "ok": ok,
            "status_code": resp.status_code,
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
        }
    except httpx.HTTPError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
        }


# ---------------------------------------------------------------- aliases


@router.get("/aliases")
async def list_aliases(
    _: None = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    rows = (await session.execute(select(Alias))).scalars().all()
    return [
        {
            "id": a.id,
            "alias_name": a.alias_name,
            "provider_id": a.provider_id,
            "upstream_model": a.upstream_model,
            "fallbacks": a.fallbacks,
            "enabled": a.enabled,
        }
        for a in rows
    ]


@router.post("/aliases", status_code=201)
async def create_alias(
    request: Request,
    body: AliasIn,
    _: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    a = Alias(**body.model_dump())
    session.add(a)
    await session.commit()
    await session.refresh(a)
    await emit(request.app, session, "alias", a.id, payload=alias_payload(a))
    await session.commit()
    return {"id": a.id, **body.model_dump()}


@router.patch("/aliases/{alias_id}")
async def update_alias(
    alias_id: int,
    body: AliasUpdate,
    request: Request,
    _: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    a = await session.get(Alias, alias_id)
    if a is None:
        raise HTTPException(404)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(a, field, value)
    await session.commit()
    await emit(request.app, session, "alias", a.id, payload=alias_payload(a))
    await session.commit()
    return {"id": a.id, **body.model_dump(exclude_unset=True)}


@router.delete("/aliases/{alias_id}", status_code=204)
async def delete_alias(
    request: Request,
    alias_id: int,
    _: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    a = await session.get(Alias, alias_id)
    if a is None:
        raise HTTPException(404)
    await emit(request.app, session, "alias", a.id, "tombstone")
    await session.delete(a)
    await session.commit()


# ---------------------------------------------------------------- prices


@router.get("/prices")
async def list_prices(
    model: str | None = None,
    current_only: bool = True,
    _: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(ModelPrice)
    if model:
        stmt = stmt.where(ModelPrice.model == model)
    if current_only:
        stmt = stmt.where(ModelPrice.effective_until.is_(None))
    rows = (await session.execute(stmt.order_by(ModelPrice.model).limit(2000))).scalars().all()
    return [
        {
            "id": b.id,
            "model": b.model,
            "effective_from": b.effective_from.isoformat(),
            "effective_until": b.effective_until.isoformat() if b.effective_until else None,
            "price_in_per_1m": round(b.price_in * 1e6, 6),
            "price_out_per_1m": round(b.price_out * 1e6, 6),
            "price_cache_read_per_1m": round(b.price_cache_read * 1e6, 6),
            "price_cache_write_per_1m": round(b.price_cache_write * 1e6, 6),
            "context_window": b.context_window,
            "source": b.source,
        }
        for b in rows
    ]


@router.post("/prices/manual", status_code=201)
async def manual_price(
    body: ManualPriceIn,
    request: Request,
    _: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    band = await set_manual(
        session,
        body.model,
        body.price_in,
        body.price_out,
        body.price_cache_read,
        body.price_cache_write,
        body.context_window,
    )
    return {"id": band.id, "model": band.model, "source": "manual"}


async def _fetch_map(request: Request, source: str) -> dict[str, PriceEntry]:
    settings: Settings = request.app.state.settings
    if source == "openrouter":
        data = (await request.app.state.http.get(settings.openrouter_models_url, timeout=30)).json()
        return parse_openrouter(data)
    url = settings.litellm_prices_url
    data = (await request.app.state.http.get(url, timeout=30)).json()
    return parse_litellm_map(data)


@router.post("/prices/refresh/preview")
async def refresh_preview(
    body: dict,
    request: Request,
    _: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Fetch + diff WITHOUT applying. The dashboard shows the diff for review."""
    source = body.get("source", "litellm")
    try:
        incoming = await _fetch_map(request, source)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"fetch failed: {exc}") from exc
    changes = await diff_against(session, incoming)
    request.app.state.price_preview = {
        "source": "litellm-live" if source == "litellm" else "openrouter",
        "changes": changes,
        "fetched_at": time.time(),
    }
    return [
        {
            "model": c.model,
            "kind": c.kind,
            "old_in_per_1m": round(c.old_in * 1e6, 6),
            "new_in_per_1m": round(c.new_in * 1e6, 6),
            "old_out_per_1m": round(c.old_out * 1e6, 6),
            "new_out_per_1m": round(c.new_out * 1e6, 6),
            "old_cache_read_per_1m": round(c.old_cache_read * 1e6, 6),
            "new_cache_read_per_1m": round(c.new_cache_read * 1e6, 6),
        }
        for c in changes[:500]
    ]


@router.post("/prices/refresh/apply")
async def refresh_apply(
    body: RefreshApply,
    request: Request,
    _: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    preview = getattr(request.app.state, "price_preview", None)
    if not preview or time.time() - preview["fetched_at"] > 600:
        raise HTTPException(409, "no recent preview — run preview first")
    changes = preview["changes"]
    if body.accept != "all":
        wanted = set(body.accept if isinstance(body.accept, list) else [body.accept])
        changes = [c for c in changes if c.model in wanted]
    n = await apply_changes(session, changes, preview["source"])
    for change in changes:
        band = await current_band(session, change.model)
        if band is not None:
            await emit(request.app, session, "price", band.id, payload=price_payload(band))
    await session.commit()
    request.app.state.price_preview = None
    return {"applied": n}


# ---------------------------------------------------------------- logs & export


def _log_filters(
    key_id: str | None,
    provider: str | None,
    model: str | None,
    status: int | None,
    instance_id: str | None,
    project: str | None,
    session: AsyncSession,
):
    conds = []
    if key_id:
        conds.append(RequestLog.key_id == key_id)
    if provider:
        conds.append(RequestLog.provider == provider)
    if model:
        conds.append(RequestLog.model == model)
    if status:
        conds.append(RequestLog.status_code == status)
    if instance_id:
        conds.append(RequestLog.instance_id == instance_id)
    return conds


@router.get("/logs")
async def query_logs(
    key_id: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    status: int | None = None,
    instance_id: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = Query(50, le=1000),
    offset: int = 0,
    _: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    from sqlalchemy import and_

    conds = _log_filters(key_id, provider, model, status, instance_id, None, session)
    if since:
        conds.append(RequestLog.ts >= datetime.fromisoformat(since))
    if until:
        conds.append(RequestLog.ts <= datetime.fromisoformat(until))
    stmt = select(RequestLog).order_by(RequestLog.ts.desc()).limit(limit).offset(offset)
    total_stmt = select(func.count(RequestLog.id))
    if conds:
        stmt = stmt.where(and_(*conds))
        total_stmt = total_stmt.where(and_(*conds))
    rows = (await session.execute(stmt)).scalars().all()
    total = (await session.execute(total_stmt)).scalar() or 0
    keys = {k.id: k for k in (await session.execute(select(VirtualKey))).scalars()}
    return {"total": total, "items": [log_out(r, keys) for r in rows]}


@router.get("/logs/export")
async def export_logs(
    format: str = "csv",
    key_id: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    status: int | None = None,
    instance_id: str | None = None,
    _: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    from sqlalchemy import and_

    conds = _log_filters(key_id, provider, model, status, instance_id, None, session)
    stmt = select(RequestLog).order_by(RequestLog.ts).limit(100_000)
    if conds:
        stmt = stmt.where(and_(*conds))
    rows = (await session.execute(stmt)).scalars().all()

    if format == "json":

        def gen():
            yield json.dumps([log_out(r) for r in rows], indent=2).encode()
    else:

        def gen():
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(log_out(rows[0]).keys() if rows else ["id"])
            yield buf.getvalue().encode()
            buf.seek(0)
            buf.truncate(0)
            for r in rows:
                writer.writerow(log_out(r).values())
                yield buf.getvalue().encode()
                buf.seek(0)
                buf.truncate(0)

    return StreamingResponse(
        gen(),
        media_type="text/csv" if format == "csv" else "application/json",
        headers={"content-disposition": f'attachment; filename="tollgate-logs.{format}"'},
    )


# ---------------------------------------------------------------- stats


@router.get("/stats")
async def get_stats(
    granularity: str = "day",
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    key_id: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    instance_id: str | None = None,
    _: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    since = datetime.fromisoformat(from_) if from_ else datetime.now(UTC) - timedelta(days=7)
    until = datetime.fromisoformat(to) if to else datetime.now(UTC)
    scope = stats_mod.Scope(key_id=key_id, provider=provider, model=model, instance_id=instance_id)
    return await stats_mod.build_stats(session, scope, since, until, granularity)


@router.get("/instances")
async def list_instances(
    _: None = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    rows = (
        await session.execute(
            select(RequestLog.instance_id, func.count(RequestLog.id)).group_by(
                RequestLog.instance_id
            )
        )
    ).all()
    return [{"instance_id": r[0], "requests": r[1]} for r in rows]


# ---------------------------------------------------------------- SSE tail


@router.get("/events/stream")
async def events_stream(request: Request, token: str = Query(None)):
    if not token or sha256_hex(token) != request.app.state.admin_token_sha256:
        raise HTTPException(401, "admin token required (pass ?token=…)")

    queue = request.app.state.events.subscribe()

    async def gen():
        try:
            yield b'event: hello\ndata: {"connected": true}\n\n'
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield b"data: " + json.dumps(event).encode() + b"\n\n"
                except TimeoutError:
                    yield b": heartbeat\n\n"
        finally:
            request.app.state.events.unsubscribe(queue)

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers={"cache-control": "no-cache"}
    )


# ---------------------------------------------------------------- settings & backup


@router.get("/settings")
async def get_settings_ep(
    request: Request, _: None = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    s: Settings = request.app.state.settings

    async def db_get(key: str):
        row = await session.get(Setting, key)
        return row.value if row else None

    return {
        "version": request.app.version,
        "retention_days": await db_get("retention_days") or s.retention_days,
        "webhook_url": await db_get("webhook_url") or "",
        "log_bodies": await db_get("log_bodies")
        if await db_get("log_bodies") is not None
        else s.log_bodies,
        "host": s.host,
        "port": s.port,
        "instance_id": request.app.state.instance_id,
        "secrets_backend": type(request.app.state.secrets._backend).__name__,
        "data_dir": str(s.data_dir),
    }


@router.put("/settings")
async def put_settings(
    request: Request,
    body: SettingsIn,
    _: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    updated = body.model_dump(exclude_unset=True, exclude_none=True)
    for key, value in updated.items():
        row = await session.get(Setting, key)
        if row:
            row.value = value
        else:
            session.add(Setting(key=key, value=value))
    await session.commit()
    for key, value in updated.items():
        await emit(
            request.app,
            session,
            "setting",
            key,
            payload=setting_payload(Setting(key=key, value=value)),
        )
    await session.commit()
    return {"ok": True, "updated": updated}


@router.post("/backup")
async def create_backup(request: Request, _: None = Depends(require_admin)):
    settings: Settings = request.app.state.settings
    # Checkpoint WAL so the copy is self-contained.
    from sqlalchemy import text

    async with request.app.state.engine.connect() as conn:
        await conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
    backups = settings.data_dir / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    name = f"tollgate-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.db"
    shutil.copy2(settings.db_path, backups / name)
    return {"name": name, "path": str(backups / name)}


@router.get("/backups")
async def list_backups(request: Request, _: None = Depends(require_admin)):
    settings: Settings = request.app.state.settings
    backups = settings.data_dir / "backups"
    if not backups.exists():
        return []
    return [f.name for f in sorted(backups.glob("*.db"), reverse=True)]


@router.post("/backups/{name}/restore")
async def restore_backup(name: str, request: Request, _: None = Depends(require_admin)):

    settings: Settings = request.app.state.settings
    src = (settings.data_dir / "backups" / name).resolve()
    if not src.exists() or src.parent != (settings.data_dir / "backups").resolve():
        raise HTTPException(404)
    shutil.copy2(src, settings.db_path)
    return {"ok": True, "note": "backup restored — restart Tollgate to use it"}


# ---------------------------------------------------------------- peers & sync


class PeerIn(BaseModel):
    name: str
    endpoint_url: str
    # Shared pairing token. Omit to generate one — it is returned ONCE; paste it
    # (with this machine's URL) into the peer's "Add peer" form on the other side.
    shared_token: str | None = None
    enabled: bool = True


def _peer_out(p, state=None) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "endpoint_url": p.endpoint_url,
        "enabled": p.enabled,
        "last_seen": p.last_seen.isoformat() if p.last_seen else None,
        "last_sent_cursor": state.last_sent_cursor if state else "",
        "last_received_cursor": state.last_received_cursor if state else "",
        "last_error": state.last_error if state else None,
    }


@router.get("/peers")
async def list_peers(
    _: None = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    from ..store.models import Peer as PeerT
    from ..store.models import SyncState

    peers = list((await session.execute(select(PeerT))).scalars())
    out = []
    for p in peers:
        state = await session.get(SyncState, p.id)
        out.append(_peer_out(p, state))
    return out


@router.post("/peers", status_code=201)
async def create_peer(
    body: PeerIn,
    request: Request,
    _: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    from ..security.secrets import generate_secret
    from ..store.models import Peer as PeerT

    token = body.shared_token or generate_secret(24)
    p = PeerT(
        name=body.name,
        endpoint_url=body.endpoint_url.rstrip("/"),
        token_hash=sha256_hex(token),
        enabled=body.enabled,
    )
    session.add(p)
    await session.flush()
    # Keep the token so we can authenticate when calling that peer.
    request.app.state.secrets.set(f"peer:{p.id}", token)
    await session.commit()
    await session.refresh(p)
    return {**_peer_out(p), "shared_token": token}  # plaintext once (if generated)


@router.patch("/peers/{peer_id}")
async def update_peer(
    peer_id: int,
    body: PeerIn,
    _: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    from ..store.models import Peer as PeerT

    p = await session.get(PeerT, peer_id)
    if p is None:
        raise HTTPException(404)
    p.name = body.name
    p.endpoint_url = body.endpoint_url.rstrip("/")
    p.enabled = body.enabled
    if body.shared_token:
        p.token_hash = sha256_hex(body.shared_token)
    await session.commit()
    return _peer_out(p)


@router.delete("/peers/{peer_id}", status_code=204)
async def delete_peer(
    peer_id: int,
    request: Request,
    _: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    from ..store.models import Peer as PeerT

    p = await session.get(PeerT, peer_id)
    if p is None:
        raise HTTPException(404)
    request.app.state.secrets.delete(f"peer:{p.id}")
    await session.delete(p)
    await session.commit()


@router.post("/sync/run")
async def run_sync(request: Request, _: None = Depends(require_admin)):
    """Exchange events with every enabled peer now (bidirectional, idempotent)."""
    from ..sync.transport import sync_all_peers

    return await sync_all_peers(request.app)


@router.get("/sync/state")
async def sync_state(
    _: None = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    """Peers + cursors + the LWW audit log (who-changed-what-when)."""
    from ..store.models import ConfigEvent as CE
    from ..store.models import Peer as PeerT
    from ..store.models import SyncState

    peers = list((await session.execute(select(PeerT))).scalars())
    peer_out = []
    for p in peers:
        state = await session.get(SyncState, p.id)
        peer_out.append(_peer_out(p, state))
    audit = (await session.execute(select(CE).order_by(CE.id.desc()).limit(50))).scalars().all()
    return {
        "peers": peer_out,
        "audit": [
            {
                "id": e.id,
                "ts": e.ts.isoformat(),
                "entity": e.entity,
                "row_pk": e.row_pk,
                "op": e.op,
                "origin_instance": e.origin_instance,
            }
            for e in audit
        ],
    }


@router.post("/sync/export")
async def sync_export(request: Request, body: dict, _: None = Depends(require_admin)):
    """Offline transport: write usage + config events to a JSON file."""
    from pathlib import Path

    from ..sync.transport import export_sync_file

    path = body.get("path")
    if not path:
        raise HTTPException(422, "path required")
    n = await export_sync_file(request.app, Path(path), body.get("cursor", ""))
    return {"written": n, "path": path}


@router.post("/sync/import")
async def sync_import(request: Request, body: dict, _: None = Depends(require_admin)):
    """Offline transport: apply a sync file produced by another instance."""
    from pathlib import Path

    from ..sync.transport import import_sync_file

    path = body.get("path")
    if not path:
        raise HTTPException(422, "path required")
    try:
        return await import_sync_file(request.app, Path(path))
    except FileNotFoundError:
        raise HTTPException(404, "file not found") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/update-check")
async def update_check(request: Request, _: None = Depends(require_admin)):
    """Compare the running version against latest.json (opt-in via
    update_manifest_url config / TOLLGATE_UPDATE_MANIFEST_URL)."""
    import itertools

    url = request.app.state.settings.update_manifest_url
    if not url:
        return {"enabled": False, "current": request.app.version}
    try:
        resp = await request.app.state.http.get(url, timeout=10.0)
        resp.raise_for_status()
        latest = (resp.json().get("version") or "").lstrip("v")
    except Exception as exc:  # noqa: BLE001 - update check must never fail hard
        return {"enabled": True, "current": request.app.version, "error": str(exc)}

    def semver(v: str):
        return tuple(int(x) if x.isdigit() else 0 for x in itertools.islice(v.split("."), 3))

    current = request.app.version
    return {
        "enabled": True,
        "current": current,
        "latest": latest,
        "up_to_date": semver(current) >= semver(latest) if latest else None,
    }
