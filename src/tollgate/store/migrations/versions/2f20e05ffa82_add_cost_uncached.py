"""add cost_uncached_usd

Revision ID: 2f20e05ffa82
Revises: eac3c7e76580
Create Date: 2026-10-02

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2f20e05ffa82"
down_revision: str | None = "eac3c7e76580"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "request_logs",
        sa.Column("cost_uncached_usd", sa.Float(), nullable=False, server_default="0.0"),
    )
    # Backfill from each row's frozen price band (bands are immutable, so
    # this yields exactly what would have been computed at log time).
    op.execute(
        """
        UPDATE request_logs
        SET cost_uncached_usd =
            (tokens_in + cache_read + cache_write) * COALESCE(b.price_in, 0)
            + tokens_out * COALESCE(b.price_out, 0)
        FROM model_prices AS b
        WHERE b.id = request_logs.price_band_id
        """
    )


def downgrade() -> None:
    op.drop_column("request_logs", "cost_uncached_usd")
