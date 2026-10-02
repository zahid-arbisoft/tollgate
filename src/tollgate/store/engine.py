"""Async engine, session factory, and programmatic Alembic upgrades."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi import Request
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _tune_sqlite(engine: AsyncEngine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragmas(dbapi_conn, _record):  # pragma: no cover - driver callback
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()


def make_engine(db_url: str) -> AsyncEngine:
    engine = create_async_engine(db_url)
    if db_url.startswith("sqlite"):
        _tune_sqlite(engine)
    return engine


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def alembic_config_for(db_url: str) -> AlembicConfig:
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    # Alembic runs on the sync driver; the app itself is async (aiosqlite).
    cfg.set_main_option("sqlalchemy.url", db_url.replace("+aiosqlite", ""))
    return cfg


def run_migrations(db_url: str) -> None:
    command.upgrade(alembic_config_for(db_url), "head")


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: session from the app-scoped factory."""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        yield session
