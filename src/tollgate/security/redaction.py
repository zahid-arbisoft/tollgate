"""Opt-in request/response previews: truncated + scrubbed (plan §12).

Body logging is OFF by default; when enabled, previews are capped and every
secret-looking pattern is masked before storage.
"""

from __future__ import annotations

import re

MAX_PREVIEW_BYTES = 2048

_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"tg-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)(x-api-key[\"\':\s]+)[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)(\"(?:api_key|password|token)\"\s*:\s*\")[^\"]+(\")"),
]


def redact(text: str) -> str:
    out = text
    out = _PATTERNS[2].sub(r"\1***", out)
    out = _PATTERNS[3].sub(r"\1***", out)
    out = _PATTERNS[4].sub(r"\1***\2", out)
    out = _PATTERNS[0].sub("sk-***", out)
    out = _PATTERNS[1].sub("tg-***", out)
    return out


def make_preview(body: bytes, limit: int = MAX_PREVIEW_BYTES) -> str:
    text = body[:limit].decode("utf-8", errors="replace")
    if len(body) > limit:
        text += f"\n...[truncated {len(body) - limit} bytes]"
    return redact(text)
