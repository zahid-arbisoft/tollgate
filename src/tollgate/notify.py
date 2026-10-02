"""Best-effort webhook notifications for limit warnings/breaches (opt-in).

URL comes from the `webhook_url` setting (Settings page). Delivery is
fire-and-forget: failures are logged, never raised — metering must not break
on a flaky webhook.
"""

from __future__ import annotations

import asyncio
import logging

from .store.models import Setting

log = logging.getLogger("tollgate.webhook")

SETTING_KEY = "webhook_url"


async def _webhook_url(app) -> str | None:
    async with app.state.session_factory() as session:
        row = await session.get(Setting, SETTING_KEY)
        return row.value if row and isinstance(row.value, str) and row.value else None


async def fire_webhook(app, payload: dict) -> None:
    url = await _webhook_url(app)
    if not url:
        return

    async def _post():
        try:
            resp = await app.state.http.post(url, json=payload, timeout=5.0)
            if resp.status_code >= 400:
                log.warning("webhook %s returned %s", url, resp.status_code)
        except Exception:  # noqa: BLE001 - never surface webhook errors
            log.warning("webhook delivery to %s failed", url, exc_info=True)

    asyncio.create_task(_post())
