"""Stats aggregation for the dashboard (scope params: key/provider/model/instance).

One pass over the filtered range: SQL GROUP BY for the time-series, in-Python
percentiles for gateway overhead (latency_total − upstream).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..store.models import RequestLog

BUCKETS = {"hour": "%Y-%m-%dT%H:00", "day": "%Y-%m-%d", "month": "%Y-%m"}


@dataclass
class Scope:
    key_id: str | None = None
    provider: str | None = None
    model: str | None = None
    instance_id: str | None = None  # None = all machines (merged view)
    project: str | None = None


def filters(scope: Scope, since: datetime, until: datetime) -> ColumnElement[bool]:
    conds: list = [RequestLog.ts >= since, RequestLog.ts <= until]
    if scope.key_id:
        conds.append(RequestLog.key_id == scope.key_id)
    if scope.provider:
        conds.append(RequestLog.provider == scope.provider)
    if scope.model:
        conds.append(RequestLog.model == scope.model)
    if scope.instance_id:
        conds.append(RequestLog.instance_id == scope.instance_id)
    return and_(*conds)


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * p
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return ordered[int(k)]
    return ordered[f] * (c - k) + ordered[c] * (k - f)


def default_range() -> tuple[datetime, datetime]:
    until = datetime.now(UTC)
    return until - timedelta(days=7), until


async def build_stats(
    session: AsyncSession,
    scope: Scope,
    since: datetime,
    until: datetime,
    granularity: str = "day",
) -> dict:
    cond = filters(scope, since, until)
    fmt = BUCKETS.get(granularity, BUCKETS["day"])
    bucket = func.strftime(fmt, RequestLog.ts).label("bucket")

    rows = (
        await session.execute(
            select(
                bucket,
                func.count(RequestLog.id),
                func.sum(RequestLog.tokens_in),
                func.sum(RequestLog.tokens_out),
                func.sum(RequestLog.cache_read + RequestLog.cache_write),
                func.sum(RequestLog.cost_usd),
                func.sum(case((RequestLog.status_code >= 400, 1), else_=0)),
                func.avg(RequestLog.latency_total_ms),
                func.avg(RequestLog.upstream_ms),
            )
            .where(cond)
            .group_by(bucket)
            .order_by(bucket)
        )
    ).all()

    series = [
        {
            "bucket": r[0],
            "requests": r[1],
            "tokens_in": r[2] or 0,
            "tokens_out": r[3] or 0,
            "tokens_cached": r[4] or 0,
            "cost_usd": round(r[5] or 0.0, 8),
            "errors": r[6] or 0,
            "avg_latency_ms": round(r[7], 2) if r[7] else None,
            "avg_upstream_ms": round(r[8], 2) if r[8] else None,
        }
        for r in rows
    ]

    total_req = sum(s["requests"] for s in series)
    total_in = sum(s["tokens_in"] for s in series)
    total_out = sum(s["tokens_out"] for s in series)
    total_cached = sum(s["tokens_cached"] for s in series)
    total_cost = sum(s["cost_usd"] for s in series)
    total_err = sum(s["errors"] for s in series)

    # Overhead percentiles from raw rows (bounded: retention window is local-scale).
    lat_rows = (
        await session.execute(
            select(RequestLog.latency_total_ms, RequestLog.upstream_ms).where(cond).limit(50_000)
        )
    ).all()
    overheads = [(t - u) for t, u in lat_rows if t is not None and u is not None and t >= u]

    async def top(column) -> list[dict]:
        tops = (
            await session.execute(
                select(column, func.count(RequestLog.id), func.sum(RequestLog.cost_usd))
                .where(cond, column.is_not(None))
                .group_by(column)
                .order_by(func.count(RequestLog.id).desc())
                .limit(8)
            )
        ).all()
        return [{"name": r[0], "requests": r[1], "cost_usd": round(r[2] or 0.0, 6)} for r in tops]

    return {
        "range": {"from": since.isoformat(), "to": until.isoformat(), "granularity": granularity},
        "summary": {
            "requests": total_req,
            "tokens_in": total_in,
            "tokens_out": total_out,
            "tokens_cached": total_cached,
            "cost_usd": round(total_cost, 8),
            "error_rate": round(total_err / total_req, 4) if total_req else 0.0,
            "overhead_p50_ms": round(percentile(overheads, 0.50), 3) if overheads else None,
            "overhead_p95_ms": round(percentile(overheads, 0.95), 3) if overheads else None,
        },
        "series": series,
        "top_keys": await top(RequestLog.key_id),
        "top_models": await top(RequestLog.model),
        "top_providers": await top(RequestLog.provider),
    }
