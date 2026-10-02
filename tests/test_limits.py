from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select

from tollgate.limits.windows import window_end, window_start
from tollgate.store.models import Counter, LimitRule

from .proxy_mock import OPENAI_KEY, openai_handler

# ---------------------------------------------------------------- window math


def test_window_minute():
    at = datetime(2026, 10, 1, 12, 34, 56, 789, tzinfo=UTC)
    assert window_start("minute", at) == datetime(2026, 10, 1, 12, 34, tzinfo=UTC)


def test_window_month_edges():
    at = datetime(2026, 1, 31, 23, 59, 59, tzinfo=UTC)
    start = window_start("month", at)
    assert (start.year, start.month) == (2026, 1)
    end = window_end("month", start)
    assert (end.year, end.month, end.day) == (2026, 2, 1)
    # December rolls into next year
    dec = window_start("month", datetime(2026, 12, 15, tzinfo=UTC))
    end = window_end("month", dec)
    assert (end.year, end.month) == (2027, 1)


def test_window_day_boundary():
    at = datetime(2026, 10, 1, 0, 0, 0, tzinfo=UTC)
    assert window_start("day", at) == at
    assert window_end("day", at) == datetime(2026, 10, 2, tzinfo=UTC)


def test_window_total_is_epoch():
    assert window_start("total") == datetime(1970, 1, 1, tzinfo=UTC)


# ---------------------------------------------------------------- enforcement


@pytest.fixture
async def proxy_ready(app, client):
    """OpenAI provider + transport mock + a virtual key."""
    async with app.state.session_factory() as s:
        from tollgate.store.models import Provider

        p = Provider(type="openai", name="openai", base_url="https://api.openai.test/v1")
        s.add(p)
        await s.flush()
        p.secret_handle = f"provider:{p.id}"
        app.state.secrets.set(p.secret_handle, OPENAI_KEY)
        await s.commit()
    old = app.state.http
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(openai_handler))
    await old.aclose()
    key, plaintext = await app.state.key_service.create(name="limits-test")
    return plaintext


async def add_rule(
    app, *, key_id=None, metric="requests", window="day", value=2, action="reject", auto_block=False
):
    async with app.state.session_factory() as s:
        s.add(
            LimitRule(
                key_id=key_id,
                metric=metric,
                window=window,
                value=value,
                action=action,
                auto_block=auto_block,
            )
        )
        await s.commit()


async def chat(client, vk):
    return await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-test", "messages": []},
        headers={"Authorization": f"Bearer {vk}"},
    )


async def test_requests_per_day_rejected_after_limit(app, client, proxy_ready):
    vk = proxy_ready
    await add_rule(app, key_id=await key_id_for(app, vk), value=2, window="day")
    assert (await chat(client, vk)).status_code == 200
    assert (await chat(client, vk)).status_code == 200
    resp = await chat(client, vk)
    assert resp.status_code == 429
    body = resp.json()
    assert body["error"]["code"] == "limit_exceeded"  # OpenAI-native shape
    assert "x-tollgate-limit-reset" in resp.headers
    assert resp.headers["x-tollgate-error"] == "limit_exceeded"


async def key_id_for(app, plaintext):
    key = await app.state.key_service.lookup_active(plaintext)
    assert key is not None
    return key.id


async def test_tokens_limit(app, client, proxy_ready):
    vk = proxy_ready
    # each successful mock call: 50 in + 12 out = 62 total tokens
    await add_rule(
        app, key_id=await key_id_for(app, vk), metric="tokens_total", window="total", value=100
    )
    await chat(client, vk)  # 62
    resp = await chat(client, vk)  # would reach 124 > 100
    assert resp.status_code == 200  # allowed: precheck sees 62 < 100
    resp = await chat(client, vk)  # now counter = 124 ≥ 100
    assert resp.status_code == 429


async def test_global_limit_applies_to_key(app, client, proxy_ready):
    vk = proxy_ready
    await add_rule(app, key_id=None, metric="requests", window="total", value=1)
    assert (await chat(client, vk)).status_code == 200
    resp = await chat(client, vk)
    assert resp.status_code == 429


async def test_auto_block_flips_key(app, client, proxy_ready):
    vk = proxy_ready
    kid = await key_id_for(app, vk)
    await add_rule(app, key_id=kid, metric="requests", window="total", value=1, auto_block=True)
    assert (await chat(client, vk)).status_code == 200
    # The breach is detected at finalize of request 1: auto-block fires there,
    # so the NEXT request fails auth (401) rather than limits (429).
    resp = await chat(client, vk)
    assert resp.status_code == 401
    key = await app.state.key_service.get(kid)
    assert key.status == "blocked"
    assert "requests total limit" in key.blocked_reason
    # unblock → auth passes again, but the counter persists → 429
    await app.state.key_service.set_status(kid, "active")
    resp = await chat(client, vk)
    assert resp.status_code == 429


async def test_warn_rule_does_not_reject(app, client, proxy_ready):
    vk = proxy_ready
    kid = await key_id_for(app, vk)
    await add_rule(app, key_id=kid, metric="requests", window="total", value=10, action="warn")
    for _ in range(10):
        assert (await chat(client, vk)).status_code == 200


async def test_failed_upstream_not_counted(app, client, proxy_ready):
    vk = proxy_ready
    kid = await key_id_for(app, vk)
    await add_rule(app, key_id=kid, metric="requests", window="total", value=5)

    def failing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    old = app.state.http
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(failing))
    for _ in range(3):
        resp = await chat(client, vk)
        assert resp.status_code == 500
    app.state.http = old  # restore, counter must still be at zero

    async with app.state.session_factory() as s:
        counters = list((await s.execute(select(Counter))).scalars())
        day = [c for c in counters if c.window == "total"]
        assert all(c.requests == 0 for c in day)


async def test_counters_increment_and_upsert(app, client, proxy_ready):
    vk = proxy_ready
    await chat(client, vk)
    await chat(client, vk)
    kid = await key_id_for(app, vk)
    async with app.state.session_factory() as s:
        counters = list((await s.execute(select(Counter))).scalars())
        rows = [c for c in counters if c.key_id == kid and c.window == "hour"]
        assert len(rows) == 1
        assert rows[0].requests == 2
        assert rows[0].tokens_in == 100  # 2 × 50
        assert rows[0].tokens_total == 124  # 2 × 62
        assert rows[0].cost_usd == 0.0  # pricing lands in Batch 5
