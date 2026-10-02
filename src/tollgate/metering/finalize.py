"""Finalize a proxied request: cost, immutable log row, counters, live event."""

from __future__ import annotations

import time

from ..pricing.calc import compute_cost
from ..store.models import RequestLog, VirtualKey
from .usage import UsageReport  # re-exported type


async def finalize_request(
    app,
    *,
    ctx,  # ProxyRequestContext
    key: VirtualKey | None,
    endpoint: str,
    provider: str | None,
    model: str | None,
    alias_used: str | None,
    status_code: int | None,
    usage: UsageReport | None,
    response_bytes: int,
    request_bytes: int,
    is_stream: bool,
    error: str | None = None,
    request_preview: str | None = None,
    response_preview: str | None = None,
) -> RequestLog | None:
    total_ms = (time.perf_counter_ns() - ctx.t0_ns) / 1e6
    upstream_ms = None
    if ctx.upstream_t0_ns and ctx.upstream_first_byte_ns:
        upstream_ms = (ctx.upstream_first_byte_ns - ctx.upstream_t0_ns) / 1e6

    tokens_in = usage.tokens_in if usage else 0
    tokens_out = usage.tokens_out if usage else 0

    cost_usd = 0.0
    band_id = None
    if usage and (tokens_in or tokens_out or usage.cache_read or usage.cache_write):
        async with app.state.session_factory() as session:
            cost_usd, band_id = await compute_cost(session, model, usage)

    row = RequestLog(
        instance_id=app.state.instance_id,
        key_id=key.id if key else None,
        provider=provider,
        model=model,
        alias_used=alias_used,
        endpoint=endpoint,
        status_code=status_code,
        latency_total_ms=total_ms,
        upstream_ms=upstream_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cache_read=usage.cache_read if usage else 0,
        cache_write=usage.cache_write if usage else 0,
        cost_usd=cost_usd,
        price_band_id=band_id,
        is_stream=is_stream,
        estimated=usage.estimated if usage else False,
        error=error,
        request_bytes=request_bytes,
        response_bytes=response_bytes,
        client_ip=ctx.client_ip,
        fallback_hops=ctx.hops or None,
        request_preview=request_preview,
        response_preview=response_preview,
    )
    async with app.state.session_factory() as session:
        session.add(row)
        await session.commit()

    # Counters + limit breach effects (Batch 4).
    from ..limits.enforcer import record_usage

    await record_usage(app, key.id if key else None, usage, cost_usd)

    app.state.events.publish(
        {
            "type": "request",
            "id": row.id,
            "ts": row.ts.isoformat(),
            "key": key.prefix if key else None,
            "key_id": key.id if key else None,
            "provider": provider,
            "model": model,
            "status": status_code,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cache_read": row.cache_read,
            "cache_write": row.cache_write,
            "cost_usd": round(cost_usd, 8),
            "latency_ms": round(total_ms, 2),
            "upstream_ms": round(upstream_ms, 2) if upstream_ms else None,
            "estimated": row.estimated,
        }
    )
    return row
