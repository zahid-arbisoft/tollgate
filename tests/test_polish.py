from __future__ import annotations

import httpx
from sqlalchemy import select

from tollgate.security.redaction import make_preview, redact
from tollgate.store.models import RequestLog, Setting

from .proxy_mock import OPENAI_KEY, openai_handler

# ---------------------------------------------------------------- redaction


def test_redact_masks_secrets():
    text = (
        "Authorization: Bearer eyJhbGciOi.very.long.token\n"
        "x-api-key: sk-ant-api03-abcdefghijklmnop\n"
        '{"api_key": "super-secret-123", "model": "gpt-4o"}\n'
        "virtual: tg-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
    )
    out = redact(text)
    assert "super-secret-123" not in out
    assert "eyJhbGciOi" not in out
    assert "sk-ant-api03-abcdefghijklmnop" not in out
    assert "AbCdEfGhIjKl" not in out
    assert "gpt-4o" in out  # non-secrets survive


def test_preview_truncates():
    preview = make_preview(b"x" * 5000)
    assert preview.startswith("x" * (2048 - 10)) or len(preview) < 2200
    assert "truncated" in preview


# ---------------------------------------------------------------- previews in pipeline


async def test_previews_off_by_default(app, client, session):
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
    _, vk = await app.state.key_service.create()

    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "secretish"}]},
        headers={"Authorization": f"Bearer {vk}"},
    )
    assert resp.status_code == 200
    async with app.state.session_factory() as s:
        log = (await s.execute(select(RequestLog))).scalars().first()
    assert log.request_preview is None  # privacy default
    assert log.response_preview is None


async def test_previews_stored_and_scrubbed_when_enabled(app, client):
    from tollgate.store.models import Provider

    async with app.state.session_factory() as s:
        s.add(Setting(key="log_bodies", value=True))
        p = Provider(type="openai", name="openai", base_url="https://api.openai.test/v1")
        s.add(p)
        await s.flush()
        p.secret_handle = f"provider:{p.id}"
        app.state.secrets.set(p.secret_handle, OPENAI_KEY)
        await s.commit()
    old = app.state.http
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(openai_handler))
    await old.aclose()
    _, vk = await app.state.key_service.create()

    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "api_key": "super-secret-123", "messages": []},
        headers={"Authorization": f"Bearer {vk}"},
    )
    assert resp.status_code == 200
    async with app.state.session_factory() as s:
        log = (await s.execute(select(RequestLog))).scalars().first()
    assert log.request_preview is not None
    assert "super-secret-123" not in log.request_preview
    assert "gpt-4o" in log.request_preview


# ---------------------------------------------------------------- update check


async def test_update_check_disabled_by_default(client, admin_headers):
    resp = await client.get("/admin/update-check", headers=admin_headers)
    body = resp.json()
    assert body["enabled"] is False
    assert body["current"]


# ---------------------------------------------------------------- webhook setting


async def test_webhook_setting_roundtrip(client, admin_headers):
    resp = await client.put(
        "/admin/settings",
        json={"webhook_url": "https://hooks.example/abc"},
        headers=admin_headers,
    )
    assert resp.json()["ok"]
    resp2 = await client.get("/admin/settings", headers=admin_headers)
    body = resp2.json()
    assert body["webhook_url"] == "https://hooks.example/abc"


# ---------------------------------------------------------------- windows db_path


def test_db_path_strips_drive_letter_slash():
    """sqlite+aiosqlite:///C:/x parses to '/C:/x' — Windows file APIs reject
    that; db_path must normalize to 'C:/x' (fixes backup/restore on Windows)."""
    from tollgate.config import Settings

    s = Settings(database_url="sqlite+aiosqlite:///C:/Users/me/data/test.db")
    assert s.db_path.as_posix() == "C:/Users/me/data/test.db"

    s2 = Settings(database_url="sqlite+aiosqlite:////tmp/abs/test.db")
    assert s2.db_path.as_posix() == "/tmp/abs/test.db"
