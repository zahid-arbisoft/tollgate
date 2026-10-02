"""Anthropic adapter: /v1/messages native passthrough + usage extraction.

Usage comes from the response `usage` block (non-stream) or the stream's
message_start / message_delta events, including cache tokens:
input_tokens, cache_read_input_tokens, cache_creation_input_tokens, output_tokens.
"""

from __future__ import annotations

from .base import ProviderAdapter, RouteContext, SSECollector, UsageReport

API_VERSION = "2023-06-01"


class AnthropicAdapter(ProviderAdapter):
    type = "anthropic"

    def upstream_url(self, base_url: str, endpoint_path: str) -> str:
        # base_url is the API root, e.g. https://api.anthropic.com
        return base_url.rstrip("/") + endpoint_path

    def auth_headers(self, api_key: str | None) -> dict[str, str]:
        headers = {"anthropic-version": API_VERSION}
        if api_key:
            headers["x-api-key"] = api_key
        return headers

    def extract_usage(
        self,
        response_json: dict | None,
        sse: SSECollector | None,
        ctx: RouteContext,
    ) -> UsageReport:
        usage: dict = {}
        if response_json is not None:
            usage = response_json.get("usage") or {}
        elif sse is not None:
            input_usage: dict = {}
            output_tokens = 0
            for ev in sse.data_events():
                if ev.get("type") == "message_start":
                    input_usage = (ev.get("message") or {}).get("usage") or {}
                elif ev.get("type") == "message_delta":
                    u = ev.get("usage") or {}
                    output_tokens = u.get("output_tokens", output_tokens)
            usage = {**input_usage, "output_tokens": output_tokens}
        return UsageReport(
            tokens_in=usage.get("input_tokens", 0) or 0,
            tokens_out=usage.get("output_tokens", 0) or 0,
            cache_read=usage.get("cache_read_input_tokens", 0) or 0,
            cache_write=usage.get("cache_creation_input_tokens", 0) or 0,
        )

    def error_payload(self, status: int, message: str, reason: str) -> dict:
        return {
            "type": "error",
            "error": {
                "type": "tollgate_error",
                "message": message,
                "reason": reason,
            },
        }
