from __future__ import annotations

import json

import httpx
import pytest

from .proxy_mock import OPENAI_KEY, openai_handler

# ---------------------------------------------------------------- auth


async def test_admin_requires_token(client):
    for path in (
        "/admin/keys",
        "/admin/limits",
        "/admin/providers",
        "/admin/logs",
        "/admin/stats",
        "/admin/settings",
    ):
        resp = await client.get(path)
        assert resp.status_code == 401, path


async def test_admin_bad_token(client):
    resp = await client.get("/admin/keys", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


# ---------------------------------------------------------------- keys CRUD


async def test_key_crud_and_actions(client, admin_headers):
    resp = await client.post(
        "/admin/keys",
        json={"name": "app", "project": "demo", "expires_in_days": 30},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    created = resp.json()
    assert created["plaintext"].startswith("tg-")
    assert created["status"] == "active"
    key_id = created["id"]

    resp = await client.get("/admin/keys", headers=admin_headers)
    assert len(resp.json()) == 1

    resp = await client.patch(
        f"/admin/keys/{key_id}", json={"notes": "updated"}, headers=admin_headers
    )
    assert resp.json()["notes"] == "updated"

    for action, expected in (
        ("disable", "disabled"),
        ("enable", "active"),
        ("block", "blocked"),
        ("unblock", "active"),
    ):
        resp = await client.post(f"/admin/keys/{key_id}/{action}", headers=admin_headers)
        assert resp.json()["status"] == expected, action

    resp = await client.post(
        f"/admin/keys/{key_id}/extend", json={"days": 7}, headers=admin_headers
    )
    assert resp.json()["expires_at"] is not None

    resp = await client.post(f"/admin/keys/{key_id}/rotate", headers=admin_headers)
    rotated = resp.json()
    assert rotated["plaintext"] != created["plaintext"]
    assert rotated["rotated_from"] == key_id

    resp = await client.delete(f"/admin/keys/{key_id}", headers=admin_headers)
    assert resp.status_code == 204
    # the rotated replacement remains until deleted too
    remaining = (await client.get("/admin/keys", headers=admin_headers)).json()
    assert [k["id"] for k in remaining] == [rotated["id"]]
    assert (
        await client.delete(f"/admin/keys/{rotated['id']}", headers=admin_headers)
    ).status_code == 204
    assert (await client.get("/admin/keys", headers=admin_headers)).json() == []


# ---------------------------------------------------------------- limits CRUD


async def test_limit_crud(client, admin_headers):
    resp = await client.post(
        "/admin/limits",
        json={"metric": "requests", "window": "day", "value": 100},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    rule = resp.json()
    assert rule["key_id"] is None  # global

    resp = await client.patch(
        f"/admin/limits/{rule['id']}", json={"value": 200}, headers=admin_headers
    )
    assert resp.json()["value"] == 200

    resp = await client.post(
        "/admin/limits",
        json={"metric": "bogus", "window": "day", "value": 1},
        headers=admin_headers,
    )
    assert resp.status_code == 422

    resp = await client.get("/admin/limits", headers=admin_headers)
    assert len(resp.json()) == 1
    assert (
        await client.delete(f"/admin/limits/{rule['id']}", headers=admin_headers)
    ).status_code == 204


# ---------------------------------------------------------------- providers


async def test_provider_crud_and_test(client, admin_headers, app):
    resp = await client.post(
        "/admin/providers",
        json={
            "type": "openai",
            "name": "openai",
            "base_url": "https://api.openai.test/v1",
            "api_key": OPENAI_KEY,
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201
    p = resp.json()
    assert p["has_key"] is True
    assert "api_key" not in p and "secret" not in json.dumps(p)  # never echoed

    # secret actually stored under provider handle
    assert app.state.secrets.get(f"provider:{p['id']}") == OPENAI_KEY

    # test-connection via mock
    old = app.state.http
    app.state.http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"data": []}))
    )
    resp = await client.post(f"/admin/providers/{p['id']}/test", headers=admin_headers)
    assert resp.json()["ok"] is True
    assert resp.json()["latency_ms"] >= 0
    app.state.http = old

    resp = await client.get("/admin/providers/presets", headers=admin_headers)
    presets = resp.json()
    assert presets["local"]["ollama"]["base_url"] == "http://localhost:11434/v1"

    resp = await client.patch(
        f"/admin/providers/{p['id']}", json={"enabled": False}, headers=admin_headers
    )
    assert resp.json()["enabled"] is False

    assert (
        await client.delete(f"/admin/providers/{p['id']}", headers=admin_headers)
    ).status_code == 204


async def test_provider_validation(client, admin_headers):
    resp = await client.post(
        "/admin/providers",
        json={"type": "bogus", "name": "x", "base_url": "http://x"},
        headers=admin_headers,
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------- aliases


async def test_alias_crud(client, admin_headers):
    presp = await client.post(
        "/admin/providers",
        json={"type": "local", "name": "ollama", "base_url": "http://localhost:11434/v1"},
        headers=admin_headers,
    )
    pid = presp.json()["id"]

    resp = await client.post(
        "/admin/aliases",
        json={"alias_name": "model-a", "provider_id": pid, "upstream_model": "llama3"},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    a = resp.json()

    resp = await client.patch(
        f"/admin/aliases/{a['id']}",
        json={"fallbacks": [{"provider_id": pid, "upstream_model": "mistral"}]},
        headers=admin_headers,
    )
    assert resp.json()["fallbacks"][0]["upstream_model"] == "mistral"

    assert (
        await client.delete(f"/admin/aliases/{a['id']}", headers=admin_headers)
    ).status_code == 204


# ---------------------------------------------------------------- prices


async def test_prices_list_and_manual(client, admin_headers):
    resp = await client.post(
        "/admin/prices/manual",
        json={"model": "llama3:8b", "price_in": 0.0, "price_out": 0.0},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    resp = await client.get("/admin/prices?model=llama3:8b", headers=admin_headers)
    bands = resp.json()
    assert bands[0]["source"] == "manual"
    assert bands[0]["price_in_per_1m"] == 0.0


async def test_price_refresh_preview_apply_flow(client, admin_headers, app):
    # seed one *bundled* band (manual bands always win and are never diffed)
    from tollgate.pricing.bands import close_and_insert
    from tollgate.pricing.loader import PriceEntry

    async with app.state.session_factory() as s:
        await close_and_insert(s, "m-x", PriceEntry("m-x", price_in=1e-6), "bundled")
        await s.commit()
    payload = {"m-x": {"input_cost_per_token": 0.000002, "output_cost_per_token": 0}}
    old = app.state.http
    app.state.http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload))
    )

    resp = await client.post(
        "/admin/prices/refresh/preview", json={"source": "litellm"}, headers=admin_headers
    )
    diff = resp.json()
    assert len(diff) == 1 and diff[0]["model"] == "m-x"
    assert diff[0]["kind"] == "changed"
    assert diff[0]["old_in_per_1m"] == 1.0 and diff[0]["new_in_per_1m"] == 2.0

    # apply only the reviewed model
    resp = await client.post(
        "/admin/prices/refresh/apply", json={"accept": ["m-x"]}, headers=admin_headers
    )
    assert resp.json()["applied"] == 1
    resp = await client.get("/admin/prices?model=m-x", headers=admin_headers)
    assert resp.json()[0]["price_in_per_1m"] == 2.0
    app.state.http = old

    # apply without preview → 409
    resp = await client.post(
        "/admin/prices/refresh/apply", json={"accept": "all"}, headers=admin_headers
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------- logs, export, stats


@pytest.fixture
async def seeded_logs(app, client, admin_headers):
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
    key, vk = await app.state.key_service.create(name="stats", project="proj-x")
    for _ in range(3):
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": []},
            headers={"Authorization": f"Bearer {vk}"},
        )
        assert resp.status_code == 200
    return key


async def test_logs_query_and_filters(client, admin_headers, seeded_logs):
    resp = await client.get("/admin/logs", headers=admin_headers)
    body = resp.json()
    assert body["total"] == 3
    item = body["items"][0]
    assert item["key"] == seeded_logs.prefix
    assert item["project"] == "proj-x"
    assert item["model"] == "gpt-4o"

    resp = await client.get("/admin/logs", params={"provider": "openai"}, headers=admin_headers)
    assert resp.json()["total"] == 3
    resp = await client.get("/admin/logs", params={"provider": "nope"}, headers=admin_headers)
    assert resp.json()["total"] == 0


async def test_logs_export_csv_and_json(client, admin_headers, seeded_logs):
    resp = await client.get("/admin/logs/export?format=csv", headers=admin_headers)
    assert resp.status_code == 200
    lines = resp.text.strip().splitlines()
    assert len(lines) == 4  # header + 3 rows

    resp = await client.get("/admin/logs/export?format=json", headers=admin_headers)
    data = json.loads(resp.text)
    assert len(data) == 3


async def test_stats_aggregation(client, admin_headers, seeded_logs, app):
    resp = await client.get("/admin/stats", params={"granularity": "day"}, headers=admin_headers)
    body = resp.json()
    summary = body["summary"]
    assert summary["requests"] == 3
    assert summary["tokens_in"] == 150  # 3 × 50
    assert summary["tokens_out"] == 36  # 3 × 12
    assert summary["tokens_cached"] == 90  # 3 × 30
    assert summary["error_rate"] == 0.0
    assert summary["overhead_p50_ms"] is not None  # overhead measurable
    assert len(body["series"]) >= 1
    assert body["top_models"][0]["name"] == "gpt-4o"

    # scope filter narrows
    resp = await client.get("/admin/stats", params={"provider": "other"}, headers=admin_headers)
    assert resp.json()["summary"]["requests"] == 0


async def test_instances_endpoint(client, admin_headers, seeded_logs, app):
    resp = await client.get("/admin/instances", headers=admin_headers)
    data = resp.json()
    assert data == [{"instance_id": app.state.instance_id, "requests": 3}]


# ---------------------------------------------------------------- settings & backup


async def test_settings_roundtrip(client, admin_headers, app):
    resp = await client.get("/admin/settings", headers=admin_headers)
    body = resp.json()
    assert body["instance_id"] == app.state.instance_id
    assert body["retention_days"] == 90

    resp = await client.put(
        "/admin/settings",
        json={"retention_days": 30, "log_bodies": False},
        headers=admin_headers,
    )
    assert resp.json()["ok"] is True
    body = (await client.get("/admin/settings", headers=admin_headers)).json()
    assert body["retention_days"] == 30


async def test_backup_and_restore(client, admin_headers, app):
    resp = await client.post("/admin/backup", headers=admin_headers)
    assert resp.status_code == 200
    name = resp.json()["name"]

    resp = await client.get("/admin/backups", headers=admin_headers)
    assert name in resp.json()

    resp = await client.post(f"/admin/backups/{name}/restore", headers=admin_headers)
    assert resp.json()["ok"] is True


# ---------------------------------------------------------------- SSE tail


async def test_events_stream_rejects_bad_token(client):
    resp = await client.get("/admin/events/stream", params={"token": "wrong"})
    assert resp.status_code == 401
    resp = await client.get("/admin/events/stream")
    assert resp.status_code == 401


async def test_event_bus_pubsub(app):
    import asyncio

    bus = app.state.events
    q = bus.subscribe()
    bus.publish({"type": "request", "model": "gpt-4o"})
    assert await asyncio.wait_for(q.get(), timeout=1) == {"type": "request", "model": "gpt-4o"}
    bus.unsubscribe(q)
    bus.publish({"type": "request"})
    assert q.empty()  # unsubscribed: no delivery
