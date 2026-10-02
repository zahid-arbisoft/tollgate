"""Provider adapter interface + SSE parsing helpers shared by all adapters."""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class UsageReport:
    tokens_in: int = 0
    tokens_out: int = 0
    cache_read: int = 0
    cache_write: int = 0
    estimated: bool = False


@dataclass
class RouteContext:
    """Everything an adapter needs to forward and meter one request."""

    provider_type: str
    base_url: str
    api_key: str | None
    endpoint_path: str  # tollgate-side path, e.g. /v1/messages
    request_body: bytes  # raw body as received (may be re-serialized after tweaks)
    is_stream: bool


@dataclass
class ProxyRequestContext:
    """Per-request state threaded through the pipeline."""

    key_id: str | None
    client_ip: str | None
    t0_ns: int
    upstream_t0_ns: int | None = None
    upstream_first_byte_ns: int | None = None
    hops: list[dict] = field(default_factory=list)


class ProviderAdapter:
    """One adapter per provider family. `local`/`openai-compatible` reuse OpenAI's."""

    type: str = "openai"

    def upstream_url(self, base_url: str, endpoint_path: str) -> str:
        raise NotImplementedError

    def auth_headers(self, api_key: str | None) -> dict[str, str]:
        raise NotImplementedError

    def prepare_body(self, body: dict) -> dict:
        """Hook to mutate the parsed JSON body before forwarding."""
        return body

    def parse_model(self, body: dict) -> str | None:
        return body.get("model")

    def extract_usage(
        self, response_json: dict | None, sse: SSECollector | None, ctx: RouteContext
    ) -> UsageReport:
        raise NotImplementedError

    def error_payload(self, status: int, message: str, reason: str) -> dict:
        """Native error shape so existing SDKs surface Tollgate errors correctly."""
        raise NotImplementedError


class SSECollector:
    """Buffers raw SSE bytes while the proxy streams them through, so usage can
    be extracted afterwards without touching the byte stream."""

    def __init__(self) -> None:
        self.chunks: list[bytes] = []
        self.total_bytes = 0

    def feed(self, chunk: bytes) -> None:
        self.chunks.append(chunk)
        self.total_bytes += len(chunk)

    @property
    def text(self) -> str:
        return b"".join(self.chunks).decode("utf-8", errors="replace")

    def data_events(self) -> list[dict]:
        """All `data:` payloads parsed as JSON (non-JSON payloads skipped)."""
        events: list[dict] = []
        for line in self.text.splitlines():
            if line.startswith("data:"):
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    events.append(json.loads(payload))
                except json.JSONDecodeError:
                    continue
        return events


def estimate_tokens_from_chars(text: str) -> int:
    """Fallback for local servers that report no usage: chars ÷ 4 (flagged)."""
    return max(1, len(text) // 4)
