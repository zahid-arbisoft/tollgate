"""FastAPI application assembly: proxy + admin + sync routers, static dashboard."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import __version__
from .admin.events import EventBus
from .config import Settings, get_settings
from .security.secrets import Secrets, generate_secret
from .store import make_engine, make_session_factory, run_migrations
from .store.models import Setting

log = logging.getLogger("tollgate")

STATIC_DIR = Path(__file__).parent / "static"

INSTANCE_KEY = "instance_id"
ADMIN_TOKEN_KEY = "admin_token_sha256"


async def _sync_loop(app: FastAPI) -> None:
    """Exchange events with paired peers every minute (idempotent; no-op
    without peers)."""
    import asyncio

    while True:
        try:
            await asyncio.sleep(60)
            from .sync.transport import sync_all_peers

            await sync_all_peers(app)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - sync must never kill the app
            log.exception("background sync failed")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level.upper())

    run_migrations(settings.db_url)
    engine = make_engine(settings.db_url)
    secrets = Secrets.create(settings.data_dir, settings.secrets_backend)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await _bootstrap(app)
        from .store.retention import retention_loop

        app.state.retention_task = asyncio.create_task(retention_loop(app))
        app.state.sync_task = asyncio.create_task(_sync_loop(app))
        yield
        for task in (app.state.sync_task, app.state.retention_task):
            task.cancel()
        await app.state.http.aclose()
        await app.state.engine.dispose()

    app = FastAPI(title="Tollgate", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.secrets = secrets
    app.state.events = EventBus()
    app.state.http = httpx.AsyncClient(follow_redirects=False)

    from .auth.dependency import AuthThrottle
    from .auth.service import KeyService

    app.state.key_service = KeyService(
        app.state.session_factory, secrets, settings.rotation_grace_seconds
    )
    app.state.auth_throttle = AuthThrottle()

    if settings.host == "127.0.0.1":  # dev convenience only: Vite on 5173
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.get("/healthz", tags=["meta"])
    async def healthz() -> dict:
        return {
            "status": "ok",
            "version": __version__,
            "instance_id": getattr(app.state, "instance_id", None),
        }

    from .admin.api import router as admin_router
    from .auth.dependency import KeyAuthError
    from .proxy.api import router as proxy_router
    from .sync.api import router as sync_router

    @app.exception_handler(KeyAuthError)
    async def key_auth_error(request: Request, exc: KeyAuthError):
        from fastapi.responses import JSONResponse

        from .proxy.providers.registry import error_payload_for_path

        payload = error_payload_for_path(
            request.url.path, exc.status_code, exc.detail or exc.reason, exc.reason
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=payload,
            headers={"x-tollgate-error": exc.reason},
        )

    app.include_router(proxy_router)
    app.include_router(admin_router, prefix="/admin")
    app.include_router(sync_router)

    if STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="dashboard")

    return app


async def ensure_admin_token(app: FastAPI) -> str:
    """Get-or-create the admin token; returns the plaintext.

    - TOLLGATE_ADMIN_TOKEN env override wins (value returned as-is).
    - Otherwise a token is generated once, its hash stored in the settings
      table, and the plaintext kept in the secret store.
    - If the hash exists but the secret is gone (secrets file lost), a new
      token is minted and the hash row updated.
    """
    from .security.hashing import sha256_hex

    settings: Settings = app.state.settings
    if settings.admin_token:
        app.state.admin_token_sha256 = sha256_hex(settings.admin_token)
        return settings.admin_token

    async with app.state.session_factory() as session:
        row = await session.get(Setting, ADMIN_TOKEN_KEY)
        token_sha: str | None = row.value if row else None
        if token_sha is None:
            token = generate_secret(24)
            app.state.secrets.set("admin-token", token)
            session.add(Setting(key=ADMIN_TOKEN_KEY, value=sha256_hex(token)))
            await session.commit()
            app.state.admin_token_sha256 = sha256_hex(token)
            return token

        stored = app.state.secrets.get("admin-token")
        if stored is not None:
            app.state.admin_token_sha256 = token_sha
            return stored

        # Hash exists but secret is unreadable — mint a fresh token.
        token = generate_secret(24)
        app.state.secrets.set("admin-token", token)
        row.value = sha256_hex(token)
        await session.commit()
        app.state.admin_token_sha256 = row.value
        return token


async def _bootstrap(app: FastAPI) -> None:
    """One-time instance identity + admin token."""
    async with app.state.session_factory() as session:
        instance_id: str | None = None
        row = await session.get(Setting, INSTANCE_KEY)
        if row is not None:
            instance_id = row.value

        if instance_id is None:
            import secrets as pysecrets

            instance_id = pysecrets.token_hex(8)
            session.add(Setting(key=INSTANCE_KEY, value=instance_id))
        await session.commit()
        app.state.instance_id = instance_id
        app.state.key_service.instance_id = instance_id

        await ensure_admin_token(app)

        settings: Settings = app.state.settings
        if settings.seed_prices:
            from .pricing.bands import ensure_seeded

            n = await ensure_seeded(session)
            if n:
                log.info("seeded %d price bands from vendored map", n)
        log.info("Tollgate ready (instance %s)", instance_id)
