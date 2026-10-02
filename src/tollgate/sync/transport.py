"""Sync transport: HTTP pull/push per peer + offline file export/import.

One `sync_peer()` run is bidirectional:
  1. PUSH our events newer than last_sent_cursor to the peer.
  2. PULL their events newer than last_received_cursor and apply locally.
Cursors are per-peer ULIDs stored in sync_state. All applies are idempotent,
so re-running after a crash or on stale cursors is always safe.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
from sqlalchemy import select

from ..store.models import ConfigEvent, Peer, RequestLog
from .merge import apply_config, apply_usage, get_or_create_sync_state
from .serialize import event_payload, log_payload

BATCH = 500


def _peer_headers(app, peer: Peer) -> dict[str, str]:
    token = app.state.secrets.get(f"peer:{peer.id}")
    return {"authorization": f"Bearer {token}"} if token else {}


async def sync_peer(app, peer: Peer, http: httpx.AsyncClient | None = None) -> dict:
    http = http or app.state.http
    result: dict = {"peer": peer.name, "pushed": 0, "pulled": 0, "error": None}
    try:
        async with app.state.session_factory() as session:
            state = await get_or_create_sync_state(session, peer.id)

            # ---- push our newest events
            logs = (
                (
                    await session.execute(
                        select(RequestLog)
                        .where(RequestLog.id > state.last_sent_cursor)
                        .order_by(RequestLog.id)
                        .limit(BATCH)
                    )
                )
                .scalars()
                .all()
            )
            cfg = (
                (
                    await session.execute(
                        select(ConfigEvent)
                        .where(ConfigEvent.id > state.last_sent_cursor)
                        .order_by(ConfigEvent.id)
                        .limit(BATCH)
                    )
                )
                .scalars()
                .all()
            )
            payload = {
                "logs": [log_payload(r) for r in logs],
                "config_events": [event_payload(e) for e in cfg],
            }

        if payload["logs"] or payload["config_events"]:
            resp = await http.post(
                f"{peer.endpoint_url.rstrip('/')}/sync/push",
                json=payload,
                headers=_peer_headers(app, peer),
                timeout=30.0,
            )
            resp.raise_for_status()
            result["pushed"] = resp.json().get("logs_applied", 0) + resp.json().get(
                "config_events_applied", 0
            )

        # ---- pull their newest events
        async with app.state.session_factory() as session:
            state = await get_or_create_sync_state(session, peer.id)
            resp = await http.get(
                f"{peer.endpoint_url.rstrip('/')}/sync/events",
                params={"cursor": state.last_received_cursor, "limit": BATCH},
                headers=_peer_headers(app, peer),
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            pulled = await apply_usage(session, data.get("logs", []))
            pulled += await apply_config(app, session, data.get("config_events", []))
            result["pulled"] = pulled

            if payload["logs"] or payload["config_events"]:
                sent_max = max([r.id for r in logs] + [e.id for e in cfg], default="")
                state.last_sent_cursor = max(state.last_sent_cursor, sent_max)
            state.last_received_cursor = data.get("next_cursor") or state.last_received_cursor
            state.last_error = None
            await session.commit()

        async with app.state.session_factory() as session:
            p = await session.get(Peer, peer.id)
            if p is not None:
                from datetime import UTC, datetime

                p.last_seen = datetime.now(UTC)
                await session.commit()
    except Exception as exc:  # noqa: BLE001 - record and continue with other peers
        result["error"] = f"{type(exc).__name__}: {exc}"
        async with app.state.session_factory() as session:
            state = await get_or_create_sync_state(session, peer.id)
            state.last_error = result["error"]
            await session.commit()
    return result


async def sync_all_peers(app) -> list[dict]:
    async with app.state.session_factory() as session:
        peers = list((await session.execute(select(Peer).where(Peer.enabled))).scalars())
    return [await sync_peer(app, peer) for peer in peers]


# ---------------------------------------------------------------- file transport


async def export_sync_file(app, path: Path, cursor: str = "") -> int:
    """Dump usage + config events newer than cursor to a JSON file."""
    async with app.state.session_factory() as session:
        logs = (
            (
                await session.execute(
                    select(RequestLog).where(RequestLog.id > cursor).order_by(RequestLog.id)
                )
            )
            .scalars()
            .all()
        )
        cfg = (
            (
                await session.execute(
                    select(ConfigEvent).where(ConfigEvent.id > cursor).order_by(ConfigEvent.id)
                )
            )
            .scalars()
            .all()
        )
    doc = {
        "format": "tollgate-sync/1",
        "instance_id": app.state.instance_id,
        "logs": [log_payload(r) for r in logs],
        "config_events": [event_payload(e) for e in cfg],
    }
    path.write_text(json.dumps(doc, indent=1))
    return len(logs) + len(cfg)


async def import_sync_file(app, path: Path) -> dict:
    doc = json.loads(path.read_text())
    if doc.get("format") != "tollgate-sync/1":
        raise ValueError("not a tollgate sync file")
    async with app.state.session_factory() as session:
        logs = await apply_usage(session, doc.get("logs", []))
        cfg = await apply_config(app, session, doc.get("config_events", []))
    return {"logs_applied": logs, "config_events_applied": cfg}
