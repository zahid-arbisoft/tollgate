from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from tollgate.store.models import Provider, RequestLog

from .proxy_mock import (
    ANTHROPIC_KEY,
    ANTHROPIC_SSE,
    OPENAI_KEY,
    OPENAI_SSE,
    anthropic_handler,
    flaky_then_ok_handler,
    local_handler,
    openai_handler,
)


@pytest.fixture
async def make_provider(app):
    async def _make(
        *, type: str, name: str, base_url: str, api_key: str | None = None, **kw
    ) -> Provider:
        async with app.state.session_factory() as s:
            p = Provider(type=type, name=name, base_url=base_url, **kw)
            s.add(p)
            if api_key is not None:
                await s.flush()  # need the id for the secret handle
                p.secret_handle = f"provider:{p.id}"
                app.state.secrets.set(p.secret_handle, api_key)
            await s.commit()
            await s.refresh(p)
            return p

    return _make


@pytest.fixture
async def vk(app):
    key, plaintext = await app.state.key_service.create(name="tests")
    return plaintext


async def use_transport(app, handler) -> None:
    old = app.state.http
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await old.aclose()


async def last_log(app) -> RequestLog | None:
    async with app.state.session_factory() as s:
        rows = list((await s.execute(select(RequestLog))).scalars())
        return rows[-1] if rows else None


# ---------------------------------------------------------------- auth e2e


async def test_missing_key_401_anthropic_shape(client):
    resp = await client.post("/v1/messages", json={"model": "m", "messages": []})
    assert resp.status_code == 401
    assert resp.json()["type"] == "error"  # Anthropic-native shape
    assert resp.headers["x-tollgate-error"] == "missing_or_malformed_key"


async def test_missing_key_401_openai_shape(client):
    resp = await client.post("/v1/chat/completions", json={"model": "m", "messages": []})
    assert resp.status_code == 401
    assert resp.json()["error"]["type"]  # OpenAI-native shape


async def test_unknown_key_401(client, vk):
    resp = await client.post(
        "/v1/messages", json={"model": "m"}, headers={"x-api-key": "tg-" + "y" * 40}
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------- anthropic


async def test_anthropic_nonstream(app, client, make_provider, vk):
    await make_provider(
        type="anthropic",
        name="anthropic",
        base_url="https://api.anthropic.test",
        api_key=ANTHROPIC_KEY,
    )
    await use_transport(app, anthropic_handler)

    resp = await client.post(
        "/v1/messages",
        json={"model": "claude-sonnet-4-5", "messages": [{"role": "user", "content": "hi"}]},
        headers={"x-api-key": vk},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["usage"]["input_tokens"] == 10
    assert resp.headers["x-tollgate-provider"] == "anthropic"
    assert resp.headers["x-tollgate-model"] == "claude-sonnet-4-5"

    log = await last_log(app)
    assert log is not None
    assert log.tokens_in == 10
    assert log.tokens_out == 20
    assert log.cache_read == 4
    assert log.cache_write == 2
    assert log.status_code == 200
    assert log.endpoint == "/v1/messages"
    assert log.upstream_ms is not None and log.latency_total_ms >= log.upstream_ms


async def test_anthropic_stream_byte_fidelity_and_usage(app, client, make_provider, vk):
    await make_provider(
        type="anthropic",
        name="anthropic",
        base_url="https://api.anthropic.test",
        api_key=ANTHROPIC_KEY,
    )
    await use_transport(app, anthropic_handler)

    resp = await client.post(
        "/v1/messages",
        json={"model": "claude-sonnet-4-5", "stream": True, "messages": []},
        headers={"x-api-key": vk},
    )
    assert resp.status_code == 200
    assert resp.content == ANTHROPIC_SSE  # byte fidelity

    log = await last_log(app)
    assert log.is_stream is True
    assert log.tokens_in == 100
    assert log.cache_read == 50
    assert log.cache_write == 10
    assert log.tokens_out == 42


# ---------------------------------------------------------------- openai


async def test_openai_nonstream_usage_split(app, client, make_provider, vk):
    await make_provider(
        type="openai",
        name="openai",
        base_url="https://api.openai.test/v1",
        api_key=OPENAI_KEY,
    )
    await use_transport(app, openai_handler)

    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-test", "messages": []},
        headers={"Authorization": f"Bearer {vk}"},
    )
    assert resp.status_code == 200
    log = await last_log(app)
    assert log.tokens_in == 50  # 80 prompt − 30 cached
    assert log.cache_read == 30
    assert log.tokens_out == 12


async def test_openai_stream_injects_usage_option(app, client, make_provider, vk):
    await make_provider(
        type="openai",
        name="openai",
        base_url="https://api.openai.test/v1",
        api_key=OPENAI_KEY,
    )
    await use_transport(app, openai_handler)

    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-test", "stream": True, "messages": []},
        headers={"Authorization": f"Bearer {vk}"},
    )
    assert resp.content == OPENAI_SSE
    log = await last_log(app)
    assert log.tokens_in == 50
    assert log.cache_read == 30
    assert log.tokens_out == 12
    assert log.is_stream is True


async def test_local_keyless_estimates_tokens(app, client, make_provider, vk):
    await make_provider(
        type="local",
        name="ollama",
        base_url="http://localhost:11434/v1",
    )
    await use_transport(app, local_handler)

    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "llama3", "stream": True, "messages": []},
        headers={"Authorization": f"Bearer {vk}"},
    )
    assert resp.status_code == 200
    log = await last_log(app)
    assert log.estimated is True
    assert log.tokens_in > 0 and log.tokens_out > 0
    assert log.provider == "ollama"


# ---------------------------------------------------------------- errors & fallback


async def test_upstream_4xx_passthrough_no_usage(app, client, make_provider, vk):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "bad request"}})

    await make_provider(
        type="openai",
        name="openai",
        base_url="https://api.openai.test/v1",
        api_key=OPENAI_KEY,
    )
    await use_transport(app, handler)
    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-test"},
        headers={"Authorization": f"Bearer {vk}"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["message"] == "bad request"
    log = await last_log(app)
    assert log.status_code == 400 and log.error == "http_400"
    assert log.tokens_in == 0  # fail closed: no usage counted


async def test_fallback_hop_on_5xx(app, client, make_provider, vk):
    await make_provider(
        type="openai",
        name="primary",
        base_url="https://primary.test/v1",
        api_key=OPENAI_KEY,
    )
    await make_provider(
        type="openai-compatible",
        name="fallback",
        base_url="https://fallback.test/v1",
        api_key=OPENAI_KEY,
    )
    await use_transport(app, flaky_then_ok_handler)

    # Alias routes to primary with fallback chain.
    async with app.state.session_factory() as s:
        providers = list((await s.execute(select(Provider))).scalars())
        by_name = {p.name: p for p in providers}
        from tollgate.store.models import Alias

        s.add(
            Alias(
                alias_name="model-a",
                provider_id=by_name["primary"].id,
                upstream_model="gpt-test",
                fallbacks=[{"provider_id": by_name["fallback"].id, "upstream_model": "gpt-test"}],
            )
        )
        await s.commit()

    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "model-a", "messages": []},
        headers={"Authorization": f"Bearer {vk}"},
    )
    assert resp.status_code == 200
    assert resp.headers["x-tollgate-provider"] == "fallback"
    assert resp.headers["x-tollgate-alias"] == "model-a"
    log = await last_log(app)
    assert log.provider == "fallback"
    assert log.alias_used == "model-a"
    assert log.fallback_hops and log.fallback_hops[0]["provider"] == "primary"


async def test_no_provider_configured_503(client, vk):
    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-test"},
        headers={"Authorization": f"Bearer {vk}"},
    )
    assert resp.status_code == 503
    assert resp.headers["x-tollgate-error"] == "no_provider"


async def test_models_lists_aliases(app, client, make_provider, vk):
    await make_provider(
        type="openai",
        name="openai",
        base_url="https://api.openai.test/v1",
        api_key=OPENAI_KEY,
    )
    async with app.state.session_factory() as s:
        from tollgate.store.models import Alias

        providers = list((await s.execute(select(Provider))).scalars())
        s.add(Alias(alias_name="model-a", provider_id=providers[0].id, upstream_model="gpt-test"))
        await s.commit()

    resp = await client.get("/v1/models", headers={"Authorization": f"Bearer {vk}"})
    assert resp.status_code == 200
    ids = [m["id"] for m in resp.json()["data"]]
    assert ids == ["model-a"]
