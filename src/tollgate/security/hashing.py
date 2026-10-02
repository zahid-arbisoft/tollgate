"""Hashing helpers for virtual-key and token verification."""

from __future__ import annotations

import hashlib


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
