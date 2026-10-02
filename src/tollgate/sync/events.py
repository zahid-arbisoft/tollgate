"""Config-event emission: every config mutation appends an immutable event.

Peers replay these with last-writer-wins (newest ULID wins per entity+row_pk).
Callers pass the session of the mutation so the event commits atomically with it.
"""

from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from ..ids import new_ulid
from ..store.models import ConfigEvent

ENTITIES = ("provider", "alias", "key", "limit", "setting", "price")


async def emit(
    app,
    session: AsyncSession,
    entity: str,
    row_pk: str,
    op: str = "upsert",
    payload: dict | None = None,
) -> None:
    assert entity in ENTITIES, entity
    assert op in ("upsert", "tombstone"), op
    session.add(
        ConfigEvent(
            id=new_ulid(),
            entity=entity,
            row_pk=str(row_pk),
            op=op,
            payload_json=json.dumps(payload, default=str) if payload is not None else None,
            origin_instance=app.state.instance_id,
            applied=True,  # local truth — we just made this change
        )
    )
