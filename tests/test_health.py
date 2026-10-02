from __future__ import annotations


async def test_healthz(client):
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["instance_id"]
    assert body["version"]


async def test_instance_id_stable(app, client):
    resp = await client.get("/healthz")
    assert resp.json()["instance_id"] == app.state.instance_id
