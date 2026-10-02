"""Atomic window counters.

SQLite treats NULLs as distinct in unique indexes, so the *global* counter uses
the sentinel key_id "" (mapped at this boundary; the rest of the app sees None).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..store.models import Counter
from .windows import WINDOWS, window_start

GLOBAL_KEY = ""  # sentinel for the global counter row


def _key(key_id: str | None) -> str:
    return key_id if key_id is not None else GLOBAL_KEY


async def add_usage(
    session: AsyncSession,
    key_id: str | None,
    *,
    requests: int,
    tokens_in: int,
    tokens_out: int,
    cost_usd: float,
    at: datetime | None = None,
) -> None:
    """Upsert-increment counters across every tracked window."""
    at = at or datetime.now(UTC)
    for window in WINDOWS:
        ws = window_start(window, at)
        stmt = sqlite_insert(Counter).values(
            key_id=_key(key_id),
            window=window,
            window_start=ws,
            requests=requests,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            tokens_total=tokens_in + tokens_out,
            cost_usd=cost_usd,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["key_id", "window", "window_start"],
            set_={
                "requests": Counter.requests + stmt.excluded.requests,
                "tokens_in": Counter.tokens_in + stmt.excluded.tokens_in,
                "tokens_out": Counter.tokens_out + stmt.excluded.tokens_out,
                "tokens_total": Counter.tokens_total + stmt.excluded.tokens_total,
                "cost_usd": Counter.cost_usd + stmt.excluded.cost_usd,
            },
        )
        await session.execute(stmt)


async def get_counters(session: AsyncSession, key_id: str | None) -> list[Counter]:
    res = await session.execute(select(Counter).where(Counter.key_id == _key(key_id)))
    return list(res.scalars())
