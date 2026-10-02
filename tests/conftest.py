"""Shared fixtures: temp data dir, settings, app, clients.

Upstream providers are always mocked via httpx.MockTransport — tests never hit
the network. `admin_headers` authenticates /admin/*.
"""

from __future__ import annotations

import pytest
import pytest_asyncio


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def settings(data_dir):
    from tollgate.config import Settings

    return Settings(
        data_dir=data_dir,
        database_url=f"sqlite+aiosqlite:///{data_dir}/test.db",
        secrets_backend="file",
        admin_token="test-admin-token",
        seed_prices=False,  # pricing tests seed explicitly
        log_level="WARNING",
    )


@pytest.fixture
def app(settings):
    from tollgate.main import create_app

    return create_app(settings)


@pytest_asyncio.fixture
async def client(app):
    from asgi_lifespan import LifespanManager
    from httpx import ASGITransport, AsyncClient

    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


@pytest.fixture
def admin_headers():
    return {"Authorization": "Bearer test-admin-token"}


@pytest_asyncio.fixture
async def session(app):
    async with app.state.session_factory() as s:
        yield s
