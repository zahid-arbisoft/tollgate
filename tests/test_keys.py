from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tollgate.auth.service import KeyService


@pytest.fixture
def svc(app) -> KeyService:
    return app.state.key_service


async def test_create_returns_plaintext_once(svc):
    key, plaintext = await svc.create(name="test")
    assert plaintext.startswith("tg-") and len(plaintext) == 3 + 40
    assert key.prefix == plaintext[:8]
    assert key.key_hash != plaintext
    import hashlib

    assert key.key_hash == hashlib.sha256(plaintext.encode()).hexdigest()
    # not stored for re-display by default
    assert await svc.stored_plaintext(key) is None


async def test_lookup_active_roundtrip(svc):
    key, plaintext = await svc.create(name="test")
    found = await svc.lookup_active(plaintext)
    assert found is not None and found.id == key.id


async def test_lookup_unknown_key(svc):
    assert await svc.lookup_active("tg-" + "x" * 40) is None


async def test_disabled_key_rejected(svc):
    key, plaintext = await svc.create()
    await svc.set_status(key.id, "disabled")
    assert await svc.lookup_active(plaintext) is None


async def test_blocked_key_rejected_with_reason(svc):
    key, plaintext = await svc.create()
    blocked = await svc.set_status(key.id, "blocked", reason="daily spend exceeded")
    assert blocked.status == "blocked"
    assert blocked.blocked_reason == "daily spend exceeded"
    assert await svc.lookup_active(plaintext) is None


async def test_expired_key_flips_status(svc):
    key, plaintext = await svc.create(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    assert await svc.lookup_active(plaintext) is None
    refetched = await svc.get(key.id)
    assert refetched.status == "expired"


async def test_rotate_grace_and_chain(svc):
    old, old_plaintext = await svc.create(name="app")
    new, new_plaintext = await svc.rotate(old.id, grace_s=60)
    assert new.rotated_from == old.id
    assert new_plaintext != old_plaintext
    # old still valid inside grace window (refetch: `old` is a stale snapshot)
    assert await svc.lookup_active(old_plaintext) is not None
    old_now = await svc.get(old.id)
    assert old_now.expires_at is not None and old_now.expires_at > datetime.now(UTC)


async def test_extend_unexpires(svc):
    key, plaintext = await svc.create(expires_in_days=1)
    await svc.set_status(key.id, "expired")
    extended = await svc.extend(key.id, days=7)
    assert extended.status == "active"
    assert await svc.lookup_active(plaintext) is not None


async def test_store_plaintext_opt_in(app):
    svc = app.state.key_service
    key, plaintext = await svc.create(store_plaintext=True)
    assert await svc.stored_plaintext(key) == plaintext
