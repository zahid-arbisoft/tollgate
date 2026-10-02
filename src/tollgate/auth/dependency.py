"""Proxy authentication: header parsing + key lookup + failure throttling.

Raises KeyAuthError; the proxy layer translates it into each provider's native
error shape so existing SDKs surface it correctly.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque

from fastapi import Request

from ..store.models import VirtualKey
from .service import KeyService

MAX_AUTH_FAILURES = 20
AUTH_FAILURE_WINDOW_S = 60.0


class KeyAuthError(Exception):
    def __init__(self, status_code: int, reason: str, detail: str | None = None):
        super().__init__(reason)
        self.status_code = status_code
        self.reason = reason
        self.detail = detail


class AuthThrottle:
    """In-memory sliding-window throttle for unknown-key attempts (per client IP)."""

    def __init__(
        self,
        max_failures: int = MAX_AUTH_FAILURES,
        window_s: float = AUTH_FAILURE_WINDOW_S,
    ):
        self._max = max_failures
        self._window = window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check_and_record(self, client_ip: str) -> bool:
        """Returns True if the client is over the limit (should be rejected)."""
        async with self._lock:
            now = time.monotonic()
            dq = self._hits[client_ip]
            while dq and dq[0] < now - self._window:
                dq.popleft()
            dq.append(now)
            return len(dq) > self._max


def extract_key(request: Request) -> str | None:
    """Anthropic-style `x-api-key` first, then OpenAI-style Bearer."""
    api_key = request.headers.get("x-api-key")
    if api_key:
        return api_key.strip()
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


async def authenticate(request: Request) -> VirtualKey:
    """FastAPI dependency for /v1/* endpoints."""
    throttle: AuthThrottle = request.app.state.auth_throttle
    plaintext = extract_key(request)
    if not plaintext or not plaintext.startswith("tg-"):
        raise KeyAuthError(
            401,
            "missing_or_malformed_key",
            "Provide a Tollgate virtual key (x-api-key or Bearer, tg-...).",
        )
    client_ip = request.client.host if request.client else "unknown"
    if await throttle.check_and_record(client_ip):
        raise KeyAuthError(429, "auth_throttled", "Too many failed attempts; slow down.")

    service: KeyService = request.app.state.key_service
    key = await service.lookup_active(plaintext)
    if key is None:
        raise KeyAuthError(401, "invalid_key", "Unknown, disabled, or expired key.")
    return key
