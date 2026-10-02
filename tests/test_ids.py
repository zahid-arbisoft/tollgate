from __future__ import annotations

import re

from tollgate.ids import new_ulid, ulid_timestamp

ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


def test_ulid_format():
    u = new_ulid()
    assert ULID_RE.match(u), u


def test_ulid_sortable():
    a, b = new_ulid(), new_ulid()
    assert (a < b) or (a > b)  # distinct
    # same-millisecond ULIDs still sort randomly but are distinct
    ids = {new_ulid() for _ in range(100)}
    assert len(ids) == 100


def test_ulid_timestamp_roundtrip():
    import time

    before = time.time()
    u = new_ulid()
    ts = ulid_timestamp(u)
    assert before - 1 <= ts <= time.time() + 1
