"""Cost calculation (plan §6), frozen at log time from the current price band.

    cost = tokens_in × price_in + tokens_out × price_out
         + cache_read × price_cache_read + cache_write × price_cache_write

The band id lands on the log row, so history never shifts when prices change.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..metering.usage import UsageReport
from .bands import current_band


async def compute_cost(
    session: AsyncSession, model: str | None, usage: UsageReport
) -> tuple[float, float, int | None]:
    """Returns (billed_cost, uncached_cost, band_id).

    billed_cost charges cached tokens at their cache rates (the estimated
    bill); uncached_cost is the counterfactual — every token at the input
    rate, i.e. what zero caching would have cost. Difference = savings.
    """
    if not model:
        return 0.0, 0.0, None
    band = await current_band(session, model)
    if band is None:
        return 0.0, 0.0, None  # unknown/local models: metered but unpriced
    cost = (
        usage.tokens_in * band.price_in
        + usage.tokens_out * band.price_out
        + usage.cache_read * band.price_cache_read
        + usage.cache_write * band.price_cache_write
    )
    uncached = (
        usage.tokens_in + usage.cache_read + usage.cache_write
    ) * band.price_in + usage.tokens_out * band.price_out
    return cost, uncached, band.id
