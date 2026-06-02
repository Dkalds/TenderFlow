"""Migración v28 — Tabla de tiers de API keys + columna tier.

Crea la tabla ``api_key_tiers`` con los tiers predefinidos y añade la
columna ``tier`` a ``api_keys`` apuntando a dicha tabla.

Tiers predefinidos:
- ``free``      — 1k req/día, 30 req/minuto.
- ``pro``       — 50k req/día, 300 req/minuto.
- ``enterprise`` — Sin límites (0 = sin límite).

Revision ID: v28_api_key_tiers
Revises: v27_csp_violations_table
Create Date: 2026-06-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v28_api_key_tiers"
down_revision: str | Sequence[str] | None = "v27_csp_violations_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS api_key_tiers (
            tier TEXT PRIMARY KEY,
            daily_quota INTEGER NOT NULL DEFAULT 10000,
            per_minute_limit INTEGER NOT NULL DEFAULT 120,
            description TEXT
        )
        """
    )
    op.execute(
        """
        INSERT OR IGNORE INTO api_key_tiers (tier, daily_quota, per_minute_limit, description)
        VALUES
            ('free',       1000,  30,  'Tier gratuito - 1k req/dia, 30 req/min'),
            ('pro',        50000, 300, 'Tier pro - 50k req/dia, 300 req/min'),
            ('enterprise', 0,     0,   'Sin limites (0 = sin limite)')
        """
    )
    try:
        op.add_column(
            "api_keys", sa.Column("tier", sa.Text(), nullable=False, server_default="free")
        )
    except Exception:
        pass


def downgrade() -> None:
    try:
        op.drop_column("api_keys", "tier")
    except Exception:
        pass
    op.execute("DROP TABLE IF EXISTS api_key_tiers")
