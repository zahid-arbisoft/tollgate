"""Mock upstreams for proxy integration tests (httpx.MockTransport — no network)."""

from __future__ import annotations

import json

import httpx

ANTHROPIC_KEY = "sk-ant-real-key"
OPENAI_KEY = "sk-openai-real-key"

ANTHROPIC_SSE = b"""event: message_start
data: {"type":"message_start","message":{"usage":{"input_tokens":100,"cache_read_input_tokens":50,"cache_creation_input_tokens":10,"output_tokens":1}}}

event: content_block_start
data: {"type":"content_block_start","index":0}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}

event: message_delta
data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":42}}

event: message_stop
data: {"type":"message_stop"}

"""

OPENAI_SSE = b"""data: {"id":"c1","choices":[{"delta":{"role":"assistant"}}]}

data: {"id":"c1","choices":[{"delta":{"content":"Hi"}}]}

data: {"id":"c1","choices":[],"usage":{"prompt_tokens":80,"completion_tokens":12,"prompt_tokens_details":{"cached_tokens":30}}}

data: [DONE]

"""

LOCAL_SSE_NO_USAGE = b"""data: {"id":"c1","choices":[{"delta":{"content":"Hello world, this is local"}}]}

data: [DONE]

"""


async def _astream(data: bytes):
    yield data


def anthropic_handler(request: httpx.Request) -> httpx.Response:
    assert request.headers.get("x-api-key") == ANTHROPIC_KEY, "real key must be injected"
    assert request.headers.get("anthropic-version")
    body = json.loads(request.content)
    if request.url.path.endswith("/count_tokens"):
        return httpx.Response(200, json={"input_tokens": 33})
    if body.get("stream"):
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_astream(ANTHROPIC_SSE),
        )
    return httpx.Response(
        200,
        json={
            "id": "msg_1",
            "model": body.get("model", "claude-sonnet-4-5"),
            "usage": {
                "input_tokens": 10,
                "output_tokens": 20,
                "cache_read_input_tokens": 4,
                "cache_creation_input_tokens": 2,
            },
        },
    )


def openai_handler(request: httpx.Request) -> httpx.Response:
    assert request.headers.get("authorization") == f"Bearer {OPENAI_KEY}"
    body = json.loads(request.content)
    if request.url.path.endswith("/models"):
        return httpx.Response(200, json={"object": "list", "data": []})
    if body.get("stream"):
        assert body.get("stream_options", {}).get("include_usage") is True, (
            "must inject stream_options.include_usage"
        )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_astream(OPENAI_SSE),
        )
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-1",
            "usage": {
                "prompt_tokens": 80,
                "completion_tokens": 12,
                "prompt_tokens_details": {"cached_tokens": 30},
            },
        },
    )


def local_handler(request: httpx.Request) -> httpx.Response:
    assert "authorization" not in request.headers, "local providers are keyless"
    body = json.loads(request.content)
    if body.get("stream"):
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_astream(LOCAL_SSE_NO_USAGE),
        )
    return httpx.Response(200, json={"id": "c1", "choices": [{"message": {"content": "hi"}}]})


def flaky_then_ok_handler(request: httpx.Request) -> httpx.Response:
    # /primary/... fails 500, /fallback/... succeeds
    if "primary" in request.url.host:
        return httpx.Response(500, json={"error": "boom"})
    return openai_handler(request)


def make_transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)
