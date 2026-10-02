"""SQLAlchemy 2 models — every table from plan §7.

Conventions:
- Money (cost_usd) and per-token prices are floats: they are estimates by design
  (provider bills are the source of truth) and SQLite Numeric maps to float anyway.
- Timestamps are timezone-aware UTC datetimes.
- request_logs / config_events rows are immutable & append-only (sync safety).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from ..ids import new_ulid


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """DateTime that always comes back tz-aware (SQLite strips tzinfo)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------- providers


class Provider(Base):
    __tablename__ = "providers"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(32))  # anthropic|openai|openai-compatible|local
    name: Mapped[str] = mapped_column(String(128), unique=True)
    base_url: Mapped[str] = mapped_column(String(512))
    # Provider API key handle in the secret store (nullable for local servers).
    secret_handle: Mapped[str | None] = mapped_column(String(128), nullable=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    timeout_s: Mapped[float] = mapped_column(default=120.0)
    retries: Mapped[int] = mapped_column(default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# ---------------------------------------------------------------- aliases


class Alias(Base):
    __tablename__ = "aliases"

    id: Mapped[int] = mapped_column(primary_key=True)
    alias_name: Mapped[str] = mapped_column(String(128), unique=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"))
    upstream_model: Mapped[str] = mapped_column(String(256))
    # Ordered fallback list: [{"provider_id": int, "upstream_model": str}, ...]
    fallbacks: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(default=True)


# ---------------------------------------------------------------- model_prices


class ModelPrice(Base):
    """Effective-dated price band. Current price = effective_until IS NULL.

    A refresh never mutates history: it closes the open band at `now` and inserts
    a new one. Request rows freeze the band they were priced with.
    """

    __tablename__ = "model_prices"

    id: Mapped[int] = mapped_column(primary_key=True)
    model: Mapped[str] = mapped_column(String(256), index=True)
    effective_from: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    effective_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)
    price_in: Mapped[float] = mapped_column(Float, default=0.0)  # USD per token
    price_out: Mapped[float] = mapped_column(Float, default=0.0)
    price_cache_read: Mapped[float] = mapped_column(Float, default=0.0)
    price_cache_write: Mapped[float] = mapped_column(Float, default=0.0)
    context_window: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="bundled")
    # bundled | litellm-live | openrouter | manual

    __table_args__ = (Index("ix_model_prices_model_current", "model", "effective_until"),)


# ---------------------------------------------------------------- virtual_keys


class VirtualKey(Base):
    __tablename__ = "virtual_keys"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_ulid)
    prefix: Mapped[str] = mapped_column(String(16), index=True)  # tg-7f3a…
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # sha256 hex
    # Opt-in "store encrypted for re-display" (off by default) — ciphertext in the
    # secret store, handle here.
    secret_handle: Mapped[str | None] = mapped_column(String(128), nullable=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    project: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # active | disabled | blocked | expired
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    rotated_from: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Allowlists (empty/None = allow all): list of provider names / model-or-alias names.
    allowed_providers: Mapped[list | None] = mapped_column(JSON, nullable=True)
    allowed_models_aliases: Mapped[list | None] = mapped_column(JSON, nullable=True)
    blocked_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)


# ---------------------------------------------------------------- limits


class LimitRule(Base):
    __tablename__ = "limits"

    id: Mapped[int] = mapped_column(primary_key=True)
    key_id: Mapped[str | None] = mapped_column(
        ForeignKey("virtual_keys.id", ondelete="CASCADE"), nullable=True, index=True
    )  # None = global
    # requests | tokens_in | tokens_out | tokens_total | cost_usd
    metric: Mapped[str] = mapped_column(String(16))
    # minute | hour | day | month | total
    window: Mapped[str] = mapped_column(String(8))
    value: Mapped[float] = mapped_column(Float)
    # reject | warn
    action: Mapped[str] = mapped_column(String(8), default="reject")
    auto_block: Mapped[bool] = mapped_column(default=False)

    __table_args__ = (UniqueConstraint("key_id", "metric", "window"),)


# ---------------------------------------------------------------- counters


class Counter(Base):
    """Window-local usage counters, one row per (key, window_start).

    key_id NULL = the global counter. Windows are calendar-aligned UTC (see
    limits/windows.py); `total` uses the epoch constant.
    """

    __tablename__ = "counters"

    id: Mapped[int] = mapped_column(primary_key=True)
    key_id: Mapped[str | None] = mapped_column(nullable=True, index=True)
    window: Mapped[str] = mapped_column(String(8))  # minute|hour|day|month|total
    window_start: Mapped[datetime] = mapped_column(UTCDateTime)
    requests: Mapped[int] = mapped_column(Integer, default=0)
    tokens_in: Mapped[int] = mapped_column(BigInteger, default=0)
    tokens_out: Mapped[int] = mapped_column(BigInteger, default=0)
    tokens_total: Mapped[int] = mapped_column(BigInteger, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)

    __table_args__ = (
        UniqueConstraint("key_id", "window", "window_start"),
        Index("ix_counters_prune", "window", "window_start"),
    )


# ---------------------------------------------------------------- request_logs


class RequestLog(Base):
    """Immutable append-only usage event. Unique on (instance_id, id) so peer
    sync merges are idempotent (INSERT OR IGNORE)."""

    __tablename__ = "request_logs"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    instance_id: Mapped[str] = mapped_column(String(32))
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    key_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    provider: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model: Mapped[str | None] = mapped_column(String(256), nullable=True)
    alias_used: Mapped[str | None] = mapped_column(String(128), nullable=True)
    endpoint: Mapped[str] = mapped_column(String(128))  # e.g. /v1/messages
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_total_ms: Mapped[int | None] = mapped_column(Float, nullable=True)
    upstream_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    tokens_in: Mapped[int] = mapped_column(BigInteger, default=0)
    tokens_out: Mapped[int] = mapped_column(BigInteger, default=0)
    cache_read: Mapped[int] = mapped_column(BigInteger, default=0)
    cache_write: Mapped[int] = mapped_column(BigInteger, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    price_band_id: Mapped[int | None] = mapped_column(ForeignKey("model_prices.id"), nullable=True)
    is_stream: Mapped[bool] = mapped_column(default=False)
    estimated: Mapped[bool] = mapped_column(default=False)  # tokens estimated (chars÷4)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    response_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    request_preview: Mapped[str | None] = mapped_column(Text, nullable=True)  # opt-in, redacted
    response_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Fallback hops taken: [{"provider": ..., "model": ..., "status": ...}, ...]
    fallback_hops: Mapped[list | None] = mapped_column(JSON, nullable=True)
    synced: Mapped[bool] = mapped_column(default=False, index=True)  # seen by peer sync

    __table_args__ = (
        UniqueConstraint("instance_id", "id"),
        Index("ix_request_logs_query", "ts", "key_id", "provider", "model"),
    )


# ---------------------------------------------------------------- sync


class Peer(Base):
    __tablename__ = "peers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    endpoint_url: Mapped[str] = mapped_column(String(512))
    token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    last_seen: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class SyncState(Base):
    __tablename__ = "sync_state"

    peer_id: Mapped[int] = mapped_column(
        ForeignKey("peers.id", ondelete="CASCADE"), primary_key=True
    )
    last_sent_cursor: Mapped[str] = mapped_column(String(26), default="")
    last_received_cursor: Mapped[str] = mapped_column(String(26), default="")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ConfigEvent(Base):
    """Config change for last-writer-wins sync (upsert or tombstone), with a
    visible audit trail (who-changed-what-when)."""

    __tablename__ = "config_events"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    entity: Mapped[str] = mapped_column(String(32))  # provider|alias|key|limit|setting|price
    row_pk: Mapped[str] = mapped_column(String(64))
    op: Mapped[str] = mapped_column(String(16))  # upsert | tombstone
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    origin_instance: Mapped[str] = mapped_column(String(32))
    applied: Mapped[bool] = mapped_column(default=False)  # applied by local LWW consumer


# ---------------------------------------------------------------- settings


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)
