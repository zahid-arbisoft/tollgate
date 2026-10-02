"""Two in-process Tollgate instances exchanging events (plan §16 'Sync')."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy import func, select

from tollgate.store.models import ConfigEvent, Peer, RequestLog, VirtualKey

from .proxy_mock import OPENAI_KEY, openai_handler

SHARED_TOKEN = "pairing-token-abc123"


async def _make_instance(data_dir):
    from tollgate.config import Settings
    from tollgate.main import create_app

    settings = Settings(
        data_dir=data_dir,
        database_url=f"sqlite+aiosqlite:///{data_dir}/test.db",
        secrets_backend="file",
        admin_token=f"admin-{data_dir.name}",
        seed_prices=False,
        log_level="WARNING",
    )
    data_dir.mkdir(parents=True, exist_ok=True)
    return create_app(settings)


@pytest_asyncio.fixture
async def pair(tmp_path):
    """Two apps: A and B. A's http client is routed to B (as if B were remote)."""
    from asgi_lifespan import LifespanManager

    app_a = await _make_instance(tmp_path / "a")
    app_b = await _make_instance(tmp_path / "b")

    async with LifespanManager(app_a), LifespanManager(app_b):
        # B keeps a normal client (no upstream providers needed); A talks to B.
        old_a = app_a.state.http
        app_a.state.http = httpx.AsyncClient(
            transport=ASGITransport(app=app_b), base_url="http://peer-b:8787"
        )
        await old_a.aclose()
        # Pairing: BOTH sides register the shared token (A→B and B→A).
        await _add_peer(app_a, "B", "http://peer-b:8787")
        await _add_peer(app_b, "A", "http://peer-a:8787")
        try:
            yield app_a, app_b
        finally:
            await app_a.state.http.aclose()
            app_a.state.http = old_a


async def _add_peer(app, name: str, url: str) -> int:
    async with app.state.session_factory() as s:
        from tollgate.security.hashing import sha256_hex

        p = Peer(name=name, endpoint_url=url, token_hash=sha256_hex(SHARED_TOKEN))
        s.add(p)
        await s.flush()
        app.state.secrets.set(f"peer:{p.id}", SHARED_TOKEN)
        await s.commit()
        return p.id


async def _count(app, model) -> int:
    async with app.state.session_factory() as s:
        return (await s.execute(select(func.count()).select_from(model))).scalar() or 0


async def _make_usage(app, model="gpt-4o") -> None:
    """Drive one proxied request through `app` (mock upstream)."""
    from tollgate.store.models import Provider as ProviderT

    async with app.state.session_factory() as s:
        p = (
            await s.execute(select(ProviderT).where(ProviderT.name == "openai"))
        ).scalar_one_or_none()
        if p is None:
            p = ProviderT(type="openai", name="openai", base_url="https://api.openai.test/v1")
            s.add(p)
            await s.flush()
            p.secret_handle = f"provider:{p.id}"
            app.state.secrets.set(p.secret_handle, OPENAI_KEY)
            await s.commit()
    old = app.state.http
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(openai_handler))
    _, plaintext = await app.state.key_service.create(name="sync-test")
    from httpx import ASGITransport as AT

    async with httpx.AsyncClient(transport=AT(app=app), base_url="http://t") as c:
        resp = await c.post(
            "/v1/chat/completions",
            json={"model": model, "messages": []},
            headers={"Authorization": f"Bearer {plaintext}"},
        )
        assert resp.status_code == 200
    await app.state.http.aclose()
    app.state.http = old


# ---------------------------------------------------------------- usage merge


async def test_usage_flows_and_merges_idempotently(pair):
    app_a, app_b = pair
    await _make_usage(app_a)
    await _make_usage(app_a)
    assert await _count(app_a, RequestLog) == 2

    from tollgate.sync.transport import sync_peer

    async with app_a.state.session_factory() as s:
        peer = await s.get(Peer, (await s.execute(select(Peer))).scalars().first().id)
        r1 = await sync_peer(app_a, peer)
    assert r1["error"] is None, r1
    assert await _count(app_b, RequestLog) == 2

    # Replay: nothing new — insert-or-ignore keeps the union stable.
    async with app_a.state.session_factory() as s:
        peer = (await s.execute(select(Peer))).scalars().first()
        r2 = await sync_peer(app_a, peer)
    assert r2["error"] is None
    assert await _count(app_b, RequestLog) == 2


# ---------------------------------------------------------------- config LWW


async def test_config_lww_newest_wins(pair):
    app_a, app_b = pair
    key, plaintext = await app_a.state.key_service.create(name="shared-key")

    async with app_a.state.session_factory() as s:
        peer = (await s.execute(select(Peer))).scalars().first()
        from tollgate.sync.transport import sync_peer

        await sync_peer(app_a, peer)

    # key landed on B
    async with app_b.state.session_factory() as s:
        copied = await s.get(VirtualKey, key.id)
    assert copied is not None and copied.name == "shared-key"
    assert copied.key_hash == key.key_hash  # same tg- key authenticates on both

    # B renames the key (newer event on B); sync again → A adopts B's name.
    async with app_b.state.session_factory() as s:
        copied = await s.get(VirtualKey, key.id)
        copied.name = "renamed-on-B"
        from tollgate.sync.events import emit
        from tollgate.sync.serialize import key_payload

        await emit(app_b, s, "key", copied.id, payload=key_payload(copied))
        await s.commit()

    old_b = app_b.state.http
    app_b.state.http = httpx.AsyncClient(
        transport=ASGITransport(app=app_a), base_url="http://peer-a:8787"
    )
    try:
        async with app_b.state.session_factory() as s:
            peer = (await s.execute(select(Peer))).scalars().first()
            r = await sync_peer(app_b, peer)
        assert r["error"] is None, r
    finally:
        await app_b.state.http.aclose()
        app_b.state.http = old_b

    key_now = await app_a.state.key_service.get(key.id)
    assert key_now.name == "renamed-on-B"  # newest won


async def test_tombstone_deletes_on_peer(pair):
    app_a, app_b = pair
    await app_a.state.key_service.create(name="doomed")

    from tollgate.sync.transport import sync_peer

    async with app_a.state.session_factory() as s:
        await sync_peer(app_a, (await s.execute(select(Peer))).scalars().first())
    assert await _count(app_b, VirtualKey) == 1

    # B deletes it → tombstone flows back to A.
    async with app_b.state.session_factory() as s:
        victim = (await s.execute(select(VirtualKey))).scalars().first()
        from tollgate.sync.events import emit

        await emit(app_b, s, "key", victim.id, "tombstone")
        await s.delete(victim)
        await s.commit()

    old_b = app_b.state.http
    app_b.state.http = httpx.AsyncClient(
        transport=ASGITransport(app=app_a), base_url="http://peer-a:8787"
    )
    try:
        async with app_b.state.session_factory() as s:
            r = await sync_peer(app_b, (await s.execute(select(Peer))).scalars().first())
        assert r["error"] is None, r
    finally:
        await app_b.state.http.aclose()
        app_b.state.http = old_b
    assert await _count(app_a, VirtualKey) == 0


# ---------------------------------------------------------------- endpoints & audit


async def test_sync_endpoints_auth_and_handshake(pair, tmp_path):
    app_a, app_b = pair
    async with httpx.AsyncClient(transport=ASGITransport(app=app_b), base_url="http://b") as c:
        r = await c.get("/sync/handshake")
        assert r.status_code == 401
        r = await c.get(
            "/sync/handshake",
            headers={"authorization": f"Bearer {SHARED_TOKEN}"},
        )
        assert r.status_code == 200  # peer registered by the fixture
        assert r.json()["instance_id"] == app_b.state.instance_id


async def test_admin_sync_state_audit(pair):
    app_a, _ = pair
    await app_a.state.key_service.create(name="audited")
    async with app_a.state.session_factory() as s:
        events = list((await s.execute(select(ConfigEvent))).scalars())
    assert len(events) == 1
    assert events[0].entity == "key"
    assert events[0].origin_instance == app_a.state.instance_id


# ---------------------------------------------------------------- file transport


async def test_file_export_import_roundtrip(pair, tmp_path: Path):
    app_a, app_b = pair
    await _make_usage(app_a)
    await app_a.state.key_service.create(name="file-key")

    from tollgate.sync.transport import export_sync_file, import_sync_file

    path = tmp_path / "bundle.json"
    written = await export_sync_file(app_a, path)
    assert written == 3  # one log row + two key events (sync-test, file-key)

    doc = json.loads(path.read_text())
    assert doc["format"] == "tollgate-sync/1"

    result = await import_sync_file(app_b, path)
    assert result["logs_applied"] == 1
    assert result["config_events_applied"] == 2
    assert await _count(app_b, RequestLog) == 1

    # import twice → idempotent
    result2 = await import_sync_file(app_b, path)
    assert result2["logs_applied"] == 0
    assert await _count(app_b, RequestLog) == 1
