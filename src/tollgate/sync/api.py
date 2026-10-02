"""Peer sync endpoints (/sync/*) — plan §8.

Auth: peers present the shared pairing token (`Authorization: Bearer <token>`)
which is checked against the peers table token_hash. The admin token is also
accepted (CLI / debugging).
"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query, Request
from sqlalchemy import select

from .. import __version__
from ..security.hashing import sha256_hex
from ..store.models import ConfigEvent, Peer, RequestLog
from .merge import apply_config, apply_usage
from .serialize import event_payload, log_payload

router = APIRouter(tags=["sync"])


async def _authorized_peer(request: Request, authorization: str | None) -> Peer | None:
    if not (authorization or "").lower().startswith("bearer "):
        raise HTTPException(401, "pairing token required")
    token = authorization[7:].strip()
    if sha256_hex(token) == request.app.state.admin_token_sha256:
        return None  # admin: allowed, not tied to a peer row
    async with request.app.state.session_factory() as session:
        peers = list((await session.execute(select(Peer))).scalars())
    for p in peers:
        if p.token_hash and p.token_hash == sha256_hex(token):
            return p
    raise HTTPException(401, "unknown pairing token")


@router.get("/sync/handshake")
async def handshake(request: Request, authorization: str | None = Header(None)):
    await _authorized_peer(request, authorization)
    return {
        "instance_id": request.app.state.instance_id,
        "version": __version__,
        "capabilities": ["usage-pull", "config-lww", "push"],
    }


@router.get("/sync/events")
async def events(
    request: Request,
    cursor: str = "",
    limit: int = Query(500, le=5000),
    authorization: str | None = Header(None),
):
    """Usage + config events with id > cursor (ULID order == time order)."""
    peer = await _authorized_peer(request, authorization)
    async with request.app.state.session_factory() as session:
        logs = (
            (
                await session.execute(
                    select(RequestLog)
                    .where(RequestLog.id > cursor)
                    .order_by(RequestLog.id)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        remaining = limit - len(logs)
        cfg = []
        if remaining > 0:
            cfg = (
                (
                    await session.execute(
                        select(ConfigEvent)
                        .where(ConfigEvent.id > cursor)
                        .order_by(ConfigEvent.id)
                        .limit(remaining)
                    )
                )
                .scalars()
                .all()
            )
        next_cursor = cursor
        for row in (*logs, *cfg):
            if row.id > next_cursor:
                next_cursor = row.id
        if peer is not None:
            from .merge import get_or_create_sync_state

            state = await get_or_create_sync_state(session, peer.id)
            state.last_seen = __import__("datetime").datetime.now(__import__("datetime").UTC)
            await session.commit()
    return {
        "logs": [log_payload(r) for r in logs],
        "config_events": [event_payload(e) for e in cfg],
        "next_cursor": next_cursor,
    }


@router.post("/sync/push")
async def push(request: Request, authorization: str | None = Header(None)):
    """Receive a peer's batch: idempotent usage merge + LWW config apply."""
    await _authorized_peer(request, authorization)
    body = await request.json()
    async with request.app.state.session_factory() as session:
        logs_applied = await apply_usage(session, body.get("logs", []))
        cfg_applied = await apply_config(request.app, session, body.get("config_events", []))
    return {"logs_applied": logs_applied, "config_events_applied": cfg_applied}
