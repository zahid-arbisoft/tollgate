"""Row ↔ dict serialization for sync payloads (JSON-safe, versioned later)."""

from __future__ import annotations

from ..store.models import (
    Alias,
    ConfigEvent,
    LimitRule,
    ModelPrice,
    Provider,
    RequestLog,
    Setting,
    VirtualKey,
)


def _dt(v):
    return v.isoformat() if v is not None else None


def provider_payload(p: Provider) -> dict:
    return {
        "id": p.id,
        "type": p.type,
        "name": p.name,
        "base_url": p.base_url,
        "secret_handle": p.secret_handle,
        "enabled": p.enabled,
        "timeout_s": p.timeout_s,
        "retries": p.retries,
        "notes": p.notes,
        "created_at": _dt(p.created_at),
    }


def alias_payload(a: Alias) -> dict:
    return {
        "id": a.id,
        "alias_name": a.alias_name,
        "provider_id": a.provider_id,
        "upstream_model": a.upstream_model,
        "fallbacks": a.fallbacks,
        "enabled": a.enabled,
    }


def key_payload(k: VirtualKey) -> dict:
    # key_hash syncs (it's how peers authenticate the same tg- key);
    # opt-in stored plaintext secrets do NOT travel.
    return {
        "id": k.id,
        "prefix": k.prefix,
        "key_hash": k.key_hash,
        "secret_handle": k.secret_handle,
        "name": k.name,
        "project": k.project,
        "status": k.status,
        "created_at": _dt(k.created_at),
        "expires_at": _dt(k.expires_at),
        "rotated_from": k.rotated_from,
        "notes": k.notes,
        "allowed_providers": k.allowed_providers,
        "allowed_models_aliases": k.allowed_models_aliases,
        "blocked_reason": k.blocked_reason,
    }


def limit_payload(r: LimitRule) -> dict:
    return {
        "id": r.id,
        "key_id": r.key_id,
        "metric": r.metric,
        "window": r.window,
        "value": r.value,
        "action": r.action,
        "auto_block": r.auto_block,
    }


def setting_payload(s: Setting) -> dict:
    return {"key": s.key, "value": s.value}


def price_payload(b: ModelPrice) -> dict:
    return {
        "id": b.id,
        "model": b.model,
        "effective_from": _dt(b.effective_from),
        "effective_until": _dt(b.effective_until),
        "price_in": b.price_in,
        "price_out": b.price_out,
        "price_cache_read": b.price_cache_read,
        "price_cache_write": b.price_cache_write,
        "context_window": b.context_window,
        "source": b.source,
    }


def log_payload(r: RequestLog) -> dict:
    return {
        "id": r.id,
        "instance_id": r.instance_id,
        "ts": _dt(r.ts),
        "key_id": r.key_id,
        "provider": r.provider,
        "model": r.model,
        "alias_used": r.alias_used,
        "endpoint": r.endpoint,
        "status_code": r.status_code,
        "latency_total_ms": r.latency_total_ms,
        "upstream_ms": r.upstream_ms,
        "tokens_in": r.tokens_in,
        "tokens_out": r.tokens_out,
        "cache_read": r.cache_read,
        "cache_write": r.cache_write,
        "cost_usd": r.cost_usd,
        "price_band_id": r.price_band_id,
        "is_stream": r.is_stream,
        "estimated": r.estimated,
        "error": r.error,
        "request_bytes": r.request_bytes,
        "response_bytes": r.response_bytes,
        "request_preview": r.request_preview,
        "response_preview": r.response_preview,
        "client_ip": r.client_ip,
        "fallback_hops": r.fallback_hops,
    }


def event_payload(e: ConfigEvent) -> dict:
    return {
        "id": e.id,
        "ts": _dt(e.ts),
        "entity": e.entity,
        "row_pk": e.row_pk,
        "op": e.op,
        "payload_json": e.payload_json,
        "origin_instance": e.origin_instance,
    }
