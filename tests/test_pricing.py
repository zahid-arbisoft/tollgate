from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from tollgate.metering.usage import UsageReport
from tollgate.pricing.bands import (
    candidate_names,
    close_and_insert,
    current_band,
    diff_against,
    ensure_seeded,
    set_manual,
)
from tollgate.pricing.calc import compute_cost
from tollgate.pricing.loader import (
    PriceEntry,
    load_vendored,
    parse_litellm_map,
    parse_openrouter,
)
from tollgate.pricing.refresh import refresh
from tollgate.store.models import ModelPrice, RequestLog

from .proxy_mock import OPENAI_KEY, openai_handler

# ---------------------------------------------------------------- loader


def test_vendored_map_loads_with_cache_rates():
    entries = load_vendored()
    assert len(entries) > 1000
    sonnet = entries["claude-sonnet-4-5"]
    assert sonnet.price_in == pytest.approx(3e-6)
    assert sonnet.price_out == pytest.approx(1.5e-5)
    assert sonnet.price_cache_read == pytest.approx(3e-7)  # cache-read discount
    assert sonnet.price_cache_write == pytest.approx(3.75e-6)  # write surcharge


def test_parse_litellm_skips_meta_keys():
    parsed = parse_litellm_map({"sample_spec": "not-a-model"})
    assert parsed == {}


def test_parse_openrouter_converts_per_million():
    parsed = parse_openrouter(
        {
            "data": [
                {"id": "m", "pricing": {"prompt": "3", "completion": "15"}, "context_length": 8192}
            ]
        }
    )
    assert parsed["m"].price_in == pytest.approx(3e-6)
    assert parsed["m"].context_window == 8192


# ---------------------------------------------------------------- resolution


def test_candidate_names():
    assert candidate_names("claude-sonnet-4-5")[0] == "claude-sonnet-4-5"
    cands = candidate_names("claude-sonnet-4-5-20250929")
    assert "claude-sonnet-4-5" in cands
    assert "anthropic/claude-sonnet-4-5" in cands
    assert "openai/gpt-4o" in candidate_names("gpt-4o")


async def test_resolve_via_prefix_and_date_strip(session):
    entry = PriceEntry("anthropic/claude-sonnet-4-5", price_in=3e-6, price_out=1.5e-5)
    await close_and_insert(session, entry.model, entry, "bundled")
    await session.commit()
    band = await current_band(session, "claude-sonnet-4-5-20250929")
    assert band is not None and band.model == "anthropic/claude-sonnet-4-5"


# ---------------------------------------------------------------- cost calc


async def test_cost_math_with_cache_split(session):
    entry = PriceEntry(
        "claude-sonnet-4-5",
        price_in=3e-6,
        price_out=1.5e-5,
        price_cache_read=3e-7,
        price_cache_write=3.75e-6,
    )
    await close_and_insert(session, entry.model, entry, "bundled")
    await session.commit()

    usage = UsageReport(tokens_in=1000, tokens_out=500, cache_read=2000, cache_write=1000)
    cost, band_id = await compute_cost(session, "claude-sonnet-4-5", usage)
    expected = 1000 * 3e-6 + 500 * 1.5e-5 + 2000 * 3e-7 + 1000 * 3.75e-6
    assert cost == pytest.approx(expected)
    assert band_id is not None


async def test_unknown_model_costs_zero(session):
    cost, band_id = await compute_cost(session, "llama3-local", UsageReport(10, 10))
    assert cost == 0.0 and band_id is None


# ---------------------------------------------------------------- THE M2 exit
# criterion: "old logs keep the old cost" after a price change


async def test_price_change_never_rewrites_history(session):
    entry = PriceEntry("gpt-x", price_in=1e-6, price_out=2e-6)
    await close_and_insert(session, entry.model, entry, "bundled")
    await session.commit()

    band1 = await current_band(session, "gpt-x")
    log1 = RequestLog(
        instance_id="test",
        endpoint="/v1/chat/completions",
        model="gpt-x",
        tokens_in=1000,
        tokens_out=1000,
        cost_usd=1000 * 1e-6 + 1000 * 2e-6,
        price_band_id=band1.id,
    )
    session.add(log1)
    await session.commit()

    # price doubles → old band closes, new band inserted
    entry2 = PriceEntry("gpt-x", price_in=2e-6, price_out=4e-6)
    await close_and_insert(session, entry2.model, entry2, "litellm-live")
    await session.commit()

    # old log row keeps its frozen cost + band
    row = (await session.execute(select(RequestLog))).scalars().first()
    assert row.cost_usd == pytest.approx(3e-3)
    assert row.price_band_id == band1.id
    band1_refreshed = await session.get(ModelPrice, band1.id)
    assert band1_refreshed.effective_until is not None  # band closed, not mutated

    # new usage prices at the NEW band
    cost2, band2_id = await compute_cost(session, "gpt-x", UsageReport(1000, 1000))
    assert cost2 == pytest.approx(6e-3)
    assert band2_id != band1.id


# ---------------------------------------------------------------- refresh


async def test_refresh_diff_and_apply(session):
    await close_and_insert(session, "model-old", PriceEntry("model-old", price_in=1e-6), "bundled")
    await close_and_insert(
        session, "model-manual", PriceEntry("model-manual", price_in=5e-6), "manual"
    )
    await session.commit()

    incoming = {
        "model-old": PriceEntry("model-old", price_in=2e-6),  # changed
        "model-manual": PriceEntry("model-manual", price_in=9e-9),  # manual wins
        "model-new": PriceEntry("model-new", price_in=1e-7),  # new
    }
    changes = await diff_against(session, incoming)
    changed = {c.model: c for c in changes}
    assert set(changed) == {"model-old", "model-new"}
    assert changed["model-old"].kind == "changed"
    assert changed["model-old"].old_in == 1e-6 and changed["model-old"].new_in == 2e-6

    from tollgate.pricing.bands import apply_changes

    await apply_changes(session, changes, "litellm-live")
    band = await current_band(session, "model-old")
    assert band.price_in == 2e-6 and band.source == "litellm-live"
    manual = await current_band(session, "model-manual")
    assert manual.price_in == 5e-6  # untouched


async def test_refresh_via_http(session):
    await close_and_insert(session, "m-r", PriceEntry("m-r", price_in=1e-6), "bundled")
    await session.commit()
    payload = {"m-r": {"input_cost_per_token": 5e-6, "output_cost_per_token": 0}}
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload))
    )
    changes = await refresh(session, http, "https://litellm.example/map.json")
    assert len(changes) == 1
    band = await current_band(session, "m-r")
    assert band.price_in == 5e-6 and band.source == "litellm-live"


async def test_seeded_bands_price_a_real_request(app, client, session):
    """End-to-end: vendored map seed → proxied request → realistic cost logged."""
    await ensure_seeded(session)
    from tollgate.store.models import Provider

    async with app.state.session_factory() as s:
        p = Provider(type="openai", name="openai", base_url="https://api.openai.test/v1")
        s.add(p)
        await s.flush()
        p.secret_handle = f"provider:{p.id}"
        app.state.secrets.set(p.secret_handle, OPENAI_KEY)
        await s.commit()
    old = app.state.http
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(openai_handler))
    await old.aclose()
    key, vk = await app.state.key_service.create()

    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": []},
        headers={"Authorization": f"Bearer {vk}"},
    )
    assert resp.status_code == 200
    async with app.state.session_factory() as s:
        log = (await s.execute(select(RequestLog))).scalars().first()
    assert log.price_band_id is not None
    # 50 uncached in + 30 cached in (at 50% discount) + 12 out at $10/1M
    expected = 50 * 2.5e-6 + 30 * 1.25e-6 + 12 * 1e-5
    assert log.cost_usd == pytest.approx(expected)


async def test_manual_entry_for_local_model(session):
    await set_manual(
        session,
        "llama3:8b",
        price_in=0.0,
        price_out=0.0,
        price_cache_read=0.0,
        price_cache_write=0.0,
    )
    band = await current_band(session, "llama3:8b")
    assert band.source == "manual"
    cost, _ = await compute_cost(session, "llama3:8b", UsageReport(100, 100))
    assert cost == 0.0
