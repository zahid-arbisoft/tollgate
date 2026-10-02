"""Limit enforcement (plan §5/§9): precheck before upstream, record at finalize.

Rules: metric ∈ {requests, tokens_in, tokens_out, tokens_total, cost_usd} ×
window ∈ {minute, hour, day, month, total} × scope ∈ {key, global}, with
action reject|warn and optional auto_block on breach.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from ..metering.usage import UsageReport
from ..notify import fire_webhook
from ..store.models import LimitRule
from .counters import add_usage, get_counters
from .windows import window_end, window_start

METRICS = ("requests", "tokens_in", "tokens_out", "tokens_total", "cost_usd")


class LimitExceeded(Exception):
    def __init__(
        self, status_code: int, reason: str, message: str, reset_at: datetime | None = None
    ):
        super().__init__(message)
        self.status_code = status_code
        self.reason = reason
        self.message = message
        self.reset_at = reset_at


def _counter_value(counter, metric: str) -> float:
    return {
        "requests": float(counter.requests),
        "tokens_in": float(counter.tokens_in),
        "tokens_out": float(counter.tokens_out),
        "tokens_total": float(counter.tokens_total),
        "cost_usd": counter.cost_usd,
    }[metric]


async def _load_rules(session, key_id: str | None) -> list[LimitRule]:
    rows = list((await session.execute(select(LimitRule))).scalars())
    return [r for r in rows if r.key_id == key_id]


async def _rules_with_counters(app, key_id: str | None):
    async with app.state.session_factory() as session:
        rules = await _load_rules(session, key_id)
        counters = {c.window: c for c in await get_counters(session, key_id)}
        # Global rules apply on top of key rules (both must pass).
        if key_id is not None:
            global_rules = await _load_rules(session, None)
            global_counters = {c.window: c for c in await get_counters(session, None)}
        else:
            global_rules, global_counters = [], {}
    return rules, counters, global_rules, global_counters


async def precheck(app, key, endpoint_path: str) -> None:
    """Fail closed before the request goes upstream. Raises LimitExceeded."""
    if key is None:
        return
    rules, counters, g_rules, g_counters = await _rules_with_counters(app, key.id)
    for scope_rules, scope_counters in ((rules, counters), (g_rules, g_counters)):
        for rule in scope_rules:
            if rule.action != "reject":
                continue
            ws = window_start(rule.window)
            counter = scope_counters.get(rule.window)
            if counter is None or counter.window_start != ws:
                continue  # nothing spent in this window yet
            if _counter_value(counter, rule.metric) >= rule.value:
                raise LimitExceeded(
                    429,
                    "limit_exceeded",
                    f"{rule.metric} limit for this {rule.window} ({rule.value:g}) exceeded.",
                    reset_at=window_end(rule.window, counter.window_start),
                )


async def record_usage(app, key_id: str | None, usage: UsageReport | None, cost_usd: float) -> None:
    """Bump counters at finalize; auto-block on breach; warn at 80%+.

    Upstream failures (usage None) never land here — fail closed, no usage
    counted (plan §9).
    """
    if usage is None:
        return

    async with app.state.session_factory() as session:
        for kid in (key_id, None):  # per-key counter + global counter
            await add_usage(
                session,
                kid,
                requests=1,
                tokens_in=usage.tokens_in,
                tokens_out=usage.tokens_out,
                cost_usd=cost_usd,
            )
        await session.commit()

    if key_id is None:
        return

    # Post-record evaluation: auto-block + warn/breach events.
    rules, counters, g_rules, g_counters = await _rules_with_counters(app, key_id)
    now = datetime.now(UTC)
    for scope_rules, scope_counters in ((rules, counters), (g_rules, g_counters)):
        for rule in scope_rules:
            ws = window_start(rule.window)
            counter = scope_counters.get(rule.window)
            if counter is None or counter.window_start != ws:
                continue
            value = _counter_value(counter, rule.metric)
            if value >= rule.value:
                if rule.auto_block:
                    await app.state.key_service.set_status(
                        key_id,
                        "blocked",
                        reason=(f"{rule.metric} {rule.window} limit ({rule.value:g}) exceeded"),
                    )
                if rule.action == "reject":
                    event = {
                        "type": "limit_exceeded",
                        "key_id": key_id,
                        "metric": rule.metric,
                        "window": rule.window,
                        "value": value,
                        "limit": rule.value,
                        "ts": now.isoformat(),
                    }
                    app.state.events.publish(event)
                    await fire_webhook(app, event)
            elif value >= 0.8 * rule.value:
                event = {
                    "type": "limit_warn",
                    "key_id": key_id,
                    "metric": rule.metric,
                    "window": rule.window,
                    "value": value,
                    "limit": rule.value,
                    "ts": now.isoformat(),
                }
                app.state.events.publish(event)
                await fire_webhook(app, event)
