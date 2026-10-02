"""OpenAI adapter — also serves openai-compatible endpoints and local servers.

For streams we inject `stream_options.include_usage` server-side so the final
chunk carries usage. Local servers (Ollama/MLX/…) often report no usage at all;
the fallback estimates tokens from payload chars (÷4) and flags `estimated`.
"""

from __future__ import annotations

import json

from .base import (
    ProviderAdapter,
    RouteContext,
    SSECollector,
    UsageReport,
    estimate_tokens_from_chars,
)


class OpenAIAdapter(ProviderAdapter):
    type = "openai"

    # openai-compatible & local servers speak the same wire format
    require_key = True
    estimate_when_missing = False

    def upstream_url(self, base_url: str, endpoint_path: str) -> str:
        # base_url already includes /v1, e.g. https://api.openai.com/v1
        suffix = endpoint_path.removeprefix("/v1")
        return base_url.rstrip("/") + suffix

    def auth_headers(self, api_key: str | None) -> dict[str, str]:
        if api_key:
            return {"Authorization": f"Bearer {api_key}"}
        return {}

    def prepare_body(self, body: dict) -> dict:
        if body.get("stream"):
            so = body.setdefault("stream_options", {})
            if isinstance(so, dict):
                so.setdefault("include_usage", True)
        return body

    def _usage_from_json(self, usage: dict) -> UsageReport:
        details = usage.get("prompt_tokens_details") or {}
        cached = details.get("cached_tokens", 0) or 0
        prompt = usage.get("prompt_tokens", 0) or 0
        return UsageReport(
            tokens_in=max(0, prompt - cached),
            tokens_out=usage.get("completion_tokens", 0) or 0,
            cache_read=cached,
        )

    def extract_usage(
        self,
        response_json: dict | None,
        sse: SSECollector | None,
        ctx: RouteContext,
    ) -> UsageReport:
        if response_json is not None:
            report = self._usage_from_json(response_json.get("usage") or {})
            if report.tokens_in or report.tokens_out or report.cache_read:
                if self.estimate_when_missing and not (report.tokens_in or report.tokens_out):
                    return self._estimate(ctx, sse)
                return report
            return self._estimate(ctx, sse)

        if sse is not None:
            for ev in reversed(sse.data_events()):
                if ev.get("usage"):
                    return self._usage_from_json(ev["usage"])
        return self._estimate(ctx, sse)

    def _estimate(self, ctx: RouteContext, sse: SSECollector | None) -> UsageReport:
        if not self.estimate_when_missing:
            return UsageReport()
        resp_text = sse.text if sse is not None else ""
        # Strip SSE envelope before counting chars so control bytes don't count.
        content_chars = sum(
            len(line[6:]) for line in resp_text.splitlines() if line.startswith("data:")
        ) or len(resp_text)
        return UsageReport(
            tokens_in=estimate_tokens_from_chars(ctx.request_body.decode("utf-8", "replace")),
            tokens_out=estimate_tokens_from_chars("x" * content_chars),
            estimated=True,
        )

    def error_payload(self, status: int, message: str, reason: str) -> dict:
        return {
            "error": {
                "message": message,
                "type": "tollgate_error",
                "code": reason,
            }
        }


class OpenAICompatAdapter(OpenAIAdapter):
    """Third-party OpenAI-compatible endpoints (Groq, Together, OpenRouter, …)."""

    type = "openai-compatible"
    require_key = False


class LocalAdapter(OpenAICompatAdapter):
    """Ollama / MLX / LM Studio / llama.cpp / vLLM — keyless, usage often absent."""

    type = "local"
    estimate_when_missing = True


def model_from_body(body: dict) -> str | None:
    m = body.get("model")
    return m if isinstance(m, str) else None


def safe_json_loads(raw: bytes) -> dict | None:
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
