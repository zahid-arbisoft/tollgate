from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tollgate.store.models import Counter, RequestLog
from tollgate.store.retention import prune


async def test_prune_removes_old_logs_and_counters(app, session):
    old = datetime.now(UTC) - timedelta(days=100)
    recent = datetime.now(UTC) - timedelta(days=1)
    for ts in (old, recent):
        session.add(RequestLog(instance_id="test", endpoint="/v1/messages", ts=ts, status_code=200))
    session.add(Counter(key_id="", window="minute", window_start=old, requests=1))
    session.add(Counter(key_id="", window="hour", window_start=old, requests=1))
    session.add(
        Counter(
            key_id="",
            window="total",
            window_start=datetime(1970, 1, 1, tzinfo=UTC),
            requests=5,
        )
    )
    await session.commit()

    removed = await prune(app)

    assert removed["request_logs"] == 1  # old log gone, recent stays
    remaining_logs = (await session.execute(select_all(RequestLog))).scalars().all()
    assert len(remaining_logs) == 1
    assert remaining_logs[0].ts > old

    # minute counters die at 2d, hour at 35d; total lives forever
    assert removed["counters_minute"] == 1
    assert removed["counters_hour"] == 1
    totals = (
        (await session.execute(select_all(Counter).where(Counter.window == "total")))
        .scalars()
        .all()
    )
    assert len(totals) == 1


def select_all(model):
    from sqlalchemy import select

    return select(model)
