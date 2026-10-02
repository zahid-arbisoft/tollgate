"""ULID generation (26-char Crockford base32, lexicographically sortable).

Vendored here to avoid a dependency; spec: https://github.com/ulid/spec
"""

from __future__ import annotations

import os
import time

_ENCODING = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32
_TIME_LEN = 10
_RANDOM_LEN = 16


def new_ulid() -> str:
    ts = time.time_ns() // 1_000_000  # ms since epoch, 48 bits
    randomness = os.urandom(10)  # 80 bits
    value = (ts << 80) | int.from_bytes(randomness, "big")
    out = [""] * 26
    for i in range(25, -1, -1):
        out[i] = _ENCODING[value & 0x1F]
        value >>= 5
    return "".join(out)


def ulid_timestamp(ulid: str) -> float:
    """Return epoch seconds encoded in a ULID (0 for invalid input)."""
    value = 0
    for ch in ulid[:_TIME_LEN]:
        idx = _ENCODING.find(ch.upper())
        if idx < 0:
            return 0.0
        value = (value << 5) | idx
    return value / 1000.0
