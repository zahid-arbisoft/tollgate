"""Calendar window math (UTC internally, local display in the UI).

Windows: minute | hour | day | month | total (the epoch constant).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

WINDOWS = ("minute", "hour", "day", "month", "total")
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def window_start(window: str, at: datetime | None = None) -> datetime:
    at = at.astimezone(UTC) if at else datetime.now(UTC)
    if window == "minute":
        return at.replace(second=0, microsecond=0)
    if window == "hour":
        return at.replace(minute=0, second=0, microsecond=0)
    if window == "day":
        return at.replace(hour=0, minute=0, second=0, microsecond=0)
    if window == "month":
        return at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if window == "total":
        return EPOCH
    raise ValueError(f"unknown window: {window}")


def window_end(window: str, start: datetime) -> datetime:
    """When the window containing `start` resets (None for `total`)."""
    if window == "minute":
        return start + timedelta(minutes=1)
    if window == "hour":
        return start + timedelta(hours=1)
    if window == "day":
        return start + timedelta(days=1)
    if window == "month":
        if start.month == 12:
            return start.replace(year=start.year + 1, month=1)
        return start.replace(month=start.month + 1)
    return datetime.max.replace(tzinfo=UTC)
