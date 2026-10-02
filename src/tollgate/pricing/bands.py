"""Temporal price bands (plan §6).

Prices are effective-dated rows: (model, effective_from, effective_until, rates,
source). Current price = the band with effective_until IS NULL. A change closes
the open band at `now` and inserts a new one — history is never mutated, so
stored log costs never shift under you.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..store.models import ModelPrice
from .loader import PriceEntry, load_vendored

_DATE_SUFFIX = re.compile(r"-\d{8}$")  # e.g. claude-sonnet-4-5-20250929
_PROVIDER_PREFIXES = ("anthropic/", "openai/", "openrouter/", "azure/", "bedrock/", "vertex_ai/")


def candidate_names(model: str) -> list[str]:
    """Ordered lookup candidates for a model name seen on the wire."""
    cands = [model]
    stripped = _DATE_SUFFIX.sub("", model)
    if stripped != model:
        cands.append(stripped)
    for prefix in _PROVIDER_PREFIXES:
        cands.append(prefix + stripped)
        cands.append(prefix + model)
    seen, out = set(), []
    for c in cands:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


async def ensure_seeded(session: AsyncSession) -> int:
    """Seed bands from the vendored map when the table is empty."""
    count = (await session.execute(select(func.count(ModelPrice.id)))).scalar() or 0
    if count:
        return 0
    entries = load_vendored()
    now = datetime.now(UTC)
    rows = [
        ModelPrice(
            model=e.model,
            effective_from=now,
            effective_until=None,
            price_in=e.price_in,
            price_out=e.price_out,
            price_cache_read=e.price_cache_read,
            price_cache_write=e.price_cache_write,
            context_window=e.context_window,
            source="bundled",
        )
        for e in entries.values()
    ]
    session.add_all(rows)
    await session.commit()
    return len(rows)


async def current_band(session: AsyncSession, model: str) -> ModelPrice | None:
    for cand in candidate_names(model):
        row = (
            await session.execute(
                select(ModelPrice)
                .where(ModelPrice.model == cand, ModelPrice.effective_until.is_(None))
                .order_by(ModelPrice.effective_from.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is not None:
            return row
    return None


async def close_and_insert(
    session: AsyncSession,
    model: str,
    entry: PriceEntry,
    source: str,
    at: datetime | None = None,
) -> ModelPrice:
    """Close the open band at `at` and insert a new one. History untouched."""
    at = at or datetime.now(UTC)
    open_band = (
        await session.execute(
            select(ModelPrice).where(
                ModelPrice.model == model, ModelPrice.effective_until.is_(None)
            )
        )
    ).scalar_one_or_none()
    if open_band is not None:
        open_band.effective_until = at
    band = ModelPrice(
        model=model,
        effective_from=at,
        effective_until=None,
        price_in=entry.price_in,
        price_out=entry.price_out,
        price_cache_read=entry.price_cache_read,
        price_cache_write=entry.price_cache_write,
        context_window=entry.context_window,
        source=source,
    )
    session.add(band)
    return band


@dataclass
class PriceChange:
    model: str
    kind: str  # changed | new
    old_in: float
    new_in: float
    old_out: float
    new_out: float
    old_cache_read: float
    new_cache_read: float
    old_cache_write: float
    new_cache_write: float
    entry: PriceEntry


async def diff_against(session: AsyncSession, incoming: dict[str, PriceEntry]) -> list[PriceChange]:
    """Diff an incoming map against current bands. Manual bands always win and
    are never reported as changed."""
    current = (
        (await session.execute(select(ModelPrice).where(ModelPrice.effective_until.is_(None))))
        .scalars()
        .all()
    )
    by_model = {b.model: b for b in current}

    changes: list[PriceChange] = []
    for model, entry in incoming.items():
        band = by_model.get(model)
        if band is None:
            changes.append(
                PriceChange(
                    model,
                    "new",
                    0,
                    entry.price_in,
                    0,
                    entry.price_out,
                    0,
                    entry.price_cache_read,
                    0,
                    entry.price_cache_write,
                    entry,
                )
            )
            continue
        if band.source == "manual":
            continue
        if (
            band.price_in == entry.price_in
            and band.price_out == entry.price_out
            and band.price_cache_read == entry.price_cache_read
            and band.price_cache_write == entry.price_cache_write
        ):
            continue
        changes.append(
            PriceChange(
                model,
                "changed",
                band.price_in,
                entry.price_in,
                band.price_out,
                entry.price_out,
                band.price_cache_read,
                entry.price_cache_read,
                band.price_cache_write,
                entry.price_cache_write,
                entry,
            )
        )
    return changes


async def apply_changes(session: AsyncSession, changes: list[PriceChange], source: str) -> int:
    for change in changes:
        await close_and_insert(session, change.model, change.entry, source)
    await session.commit()
    return len(changes)


async def set_manual(
    session: AsyncSession,
    model: str,
    price_in: float,
    price_out: float,
    price_cache_read: float,
    price_cache_write: float,
    context_window: int | None = None,
) -> ModelPrice:
    """Manual entries win over every fetched map (also used for local models)."""
    entry = PriceEntry(
        model=model,
        price_in=price_in,
        price_out=price_out,
        price_cache_read=price_cache_read,
        price_cache_write=price_cache_write,
        context_window=context_window,
    )
    band = await close_and_insert(session, model, entry, "manual")
    await session.commit()
    return band
