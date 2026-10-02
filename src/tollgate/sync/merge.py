"""Merge logic: usage logs (idempotent union) + config events (LWW).

Usage rows are append-only with a global ULID id — merging is INSERT OR IGNORE
on (instance_id, id); no conflicts are possible by construction.

Config: newest event per (entity, row_pk) wins, where "newest" is the highest
event ULID (lexicographic == chronological). Applied events are stored, which
both dedupes replays and forms the visible audit log.
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..store.models import (
    Alias,
    ConfigEvent,
    LimitRule,
    ModelPrice,
    Provider,
    RequestLog,
    Setting,
    SyncState,
    VirtualKey,
)

LOG_COLUMNS = {c.name for c in RequestLog.__table__.columns}


def _parse_dt(v: str | None) -> datetime | None:
    return datetime.fromisoformat(v) if v else None


async def apply_usage(session: AsyncSession, logs: list[dict]) -> int:
    """INSERT OR IGNORE usage rows; returns how many were new."""
    applied = 0
    for row in logs:
        data = {k: v for k, v in row.items() if k in LOG_COLUMNS}
        data["ts"] = _parse_dt(data.get("ts"))
        stmt = sqlite_insert(RequestLog).values(**data)
        stmt = stmt.on_conflict_do_nothing(index_elements=["instance_id", "id"])
        res = await session.execute(stmt)
        applied += res.rowcount or 0
    await session.commit()
    return applied


async def _latest_event_id(session: AsyncSession, entity: str, row_pk: str) -> str | None:
    return (
        await session.execute(
            select(ConfigEvent.id)
            .where(ConfigEvent.entity == entity, ConfigEvent.row_pk == row_pk)
            .order_by(ConfigEvent.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


_APPLIERS = {}


async def _upsert(session, model, pk, payload: dict):
    row = await session.get(model, pk)
    if row is None:
        session.add(model(**payload))
    else:
        for k, v in payload.items():
            setattr(row, k, v)


async def _apply_provider(session, payload: dict):
    await _upsert(session, Provider, payload["id"], payload)


async def _apply_alias(session, payload: dict):
    await _upsert(session, Alias, payload["id"], payload)


async def _apply_key(session, payload: dict):
    await _upsert(session, VirtualKey, payload["id"], payload)


async def _apply_limit(session, payload: dict):
    await _upsert(session, LimitRule, payload["id"], payload)


async def _apply_setting(session, payload: dict):
    await _upsert(session, Setting, payload["key"], payload)


async def _apply_price(session, payload: dict):
    # Bands are effective-dated and append-only: upsert by id, never delete.
    payload = dict(payload)
    payload["effective_from"] = _parse_dt(payload.get("effective_from"))
    payload["effective_until"] = _parse_dt(payload.get("effective_until"))
    await _upsert(session, ModelPrice, payload["id"], payload)


_APPLIERS = {
    "provider": _apply_provider,
    "alias": _apply_alias,
    "key": _apply_key,
    "limit": _apply_limit,
    "setting": _apply_setting,
    "price": _apply_price,
}

_TOMBSTONES = {
    "provider": Provider,
    "alias": Alias,
    "key": VirtualKey,
    "limit": LimitRule,
    "setting": Setting,
}


async def apply_config(app, session: AsyncSession, events: list[dict]) -> int:
    """Apply config events newest-wins; returns how many were applied."""
    applied = 0
    for ev in events:
        entity, row_pk, ev_id = ev["entity"], ev["row_pk"], ev["id"]
        if await session.get(ConfigEvent, ev_id) is not None:
            continue  # replay / echo of our own event
        latest = await _latest_event_id(session, entity, row_pk)
        if latest is not None and latest >= ev_id:
            continue  # we already have a newer (or the same) state

        payload = json.loads(ev["payload_json"]) if ev.get("payload_json") else None
        if ev["op"] == "tombstone" and entity in _TOMBSTONES:
            model = _TOMBSTONES[entity]
            pk = int(row_pk) if entity in ("provider", "alias", "limit") else row_pk
            row = await session.get(model, pk)
            if row is not None:
                await session.delete(row)
        elif ev["op"] == "upsert" and payload is not None:
            data = dict(payload)
            for field in ("created_at", "expires_at"):
                if field in data:
                    data[field] = _parse_dt(data[field])
            await _APPLIERS[entity](session, data)

        session.add(
            ConfigEvent(
                id=ev_id,
                ts=_parse_dt(ev.get("ts")),
                entity=entity,
                row_pk=row_pk,
                op=ev["op"],
                payload_json=ev.get("payload_json"),
                origin_instance=ev.get("origin_instance", ""),
                applied=True,
            )
        )
        applied += 1
    await session.commit()
    return applied


async def get_or_create_sync_state(session: AsyncSession, peer_id: int) -> SyncState:
    state = await session.get(SyncState, peer_id)
    if state is None:
        state = SyncState(peer_id=peer_id)
        session.add(state)
        await session.commit()
    return state
