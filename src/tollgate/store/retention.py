"""Retention: hourly prune of old request_logs rows and window counters.

request_logs older than `retention_days` are deleted (they're usage events, not
billing records). Counters outlive their windows only long enough to serve the
dashboard: minute windows for 2 days, hour for 35, day for 95, month for 400;
`total` counters are kept forever.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from ..store.models import Counter, Setting

log = logging.getLogger("tollgate.retention")

RETENTION_KEY = "retention_days"
COUNTER_HORIZONS = {"minute": 2, "hour": 35, "day": 95, "month": 400}
PRUNE_INTERVAL_S = 3600


async def prune(app) -> dict[str, int]:
    """One prune pass. Returns rows deleted per table."""
    from ..store.models import RequestLog as RL

    now = datetime.now(UTC)
    removed: dict[str, int] = {}

    async with app.state.session_factory() as session:
        row = await session.get(Setting, RETENTION_KEY)
        days = int(row.value) if row else app.state.settings.retention_days
        if days > 0:
            cutoff = now - timedelta(days=days)
            res = await session.execute(delete(RL).where(RL.ts < cutoff))
            removed["request_logs"] = res.rowcount or 0

        for window, horizon_days in COUNTER_HORIZONS.items():
            cutoff = now - timedelta(days=horizon_days)
            res = await session.execute(
                delete(Counter).where(Counter.window == window, Counter.window_start < cutoff)
            )
            removed[f"counters_{window}"] = res.rowcount or 0
        await session.commit()

    if any(removed.values()):
        log.info("retention prune: %s", removed)
    return removed


async def retention_loop(app) -> None:
    """Long-running prune task started by the app lifespan."""
    while True:
        try:
            await asyncio.sleep(PRUNE_INTERVAL_S)
            await prune(app)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - pruning must never kill the app
            log.exception("retention prune failed")
