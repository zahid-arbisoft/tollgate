"""Typed configuration (pydantic-settings).

All values can be overridden with `TOLLGATE_*` environment variables, e.g.
`TOLLGATE_PORT=9000`. The data directory holds the SQLite database, the
encrypted-secrets fallback file, and runtime state.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import platformdirs
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_NAME = "Tollgate"


def default_data_dir() -> Path:
    return platformdirs.user_data_path(APP_NAME)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="tollgate_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    data_dir: Path = Field(default_factory=default_data_dir)
    host: str = "127.0.0.1"
    port: int = 8787

    # Explicit DB override (e.g. tests: sqlite+aiosqlite:/:memory: is not supported;
    # use a temp file). When None, derives from data_dir.
    database_url: str | None = None

    # Auth bootstrap: when set, used as the admin token instead of the generated one.
    admin_token: str | None = None

    # Secrets: auto (keyring w/ file fallback) | keyring | file
    secrets_backend: str = "auto"

    # Log retention for request_logs / summarized counters (days).
    retention_days: int = 90

    # Opt-in request/response body previews (redacted + truncated) — off by default.
    log_bodies: bool = False

    # In-app update check manifest (empty = disabled). Points at the
    # latest.json artifact published with GitHub Releases.
    update_manifest_url: str = ""

    # Price refresh sources (Batch 5).
    litellm_prices_url: str = (
        "https://raw.githubusercontent.com/BerriAI/litellm/main/"
        "model_prices_and_context_window.json"
    )
    openrouter_models_url: str = "https://openrouter.ai/api/v1/models"

    # Seconds a rotated key keeps working before expiring.
    rotation_grace_seconds: int = 3600

    # Seed price bands from the vendored map on first boot.
    seed_prices: bool = True

    log_level: str = "INFO"

    @property
    def db_path(self) -> Path:
        if self.database_url:
            from urllib.parse import urlparse

            return Path(urlparse(self.database_url).path)
        return self.data_dir / "tollgate.db"

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite+aiosqlite:///{self.db_path}"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings
