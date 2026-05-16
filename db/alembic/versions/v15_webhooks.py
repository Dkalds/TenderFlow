"""add webhooks table and api_keys.expires_at for B5+B6

Revision ID: v15_webhooks
Revises: v14_ml_feedback
Create Date: 2026-05-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v15_webhooks"
down_revision: str | Sequence[str] | None = "v14_ml_feedback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Tabla webhooks (B5)
    op.create_table(
        "webhooks",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("secret", sa.Text, nullable=False),  # HMAC-SHA256 signing
        sa.Column("event_types", sa.Text, nullable=False),  # CSV: "watchlist_match,daily_summary"
        sa.Column("active", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("last_triggered_at", sa.Text, nullable=True),
        sa.Column("last_status", sa.Integer, nullable=True),
        sa.Column("failure_count", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("idx_webhooks_active", "webhooks", ["active"])

    # Añadir expires_at a api_keys (B6) — solo si la columna no existe
    # SQLite no soporta IF NOT EXISTS para ADD COLUMN, manejarlo con try/except en op
    with op.get_context().autocommit_block():
        conn = op.get_bind()
        result = conn.execute(sa.text("PRAGMA table_info(api_keys)"))
        existing = {row[1] for row in result} if result is not None else set()
        if "expires_at" not in existing:
            op.add_column("api_keys", sa.Column("expires_at", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_index("idx_webhooks_active", "webhooks")
    op.drop_table("webhooks")
    # SQLite no soporta DROP COLUMN antes de 3.35; omitimos rollback de expires_at
