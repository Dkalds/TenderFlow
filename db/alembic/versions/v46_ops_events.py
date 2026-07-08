"""Migracion v46 -- tabla ops_events para tripwires de persistencia.

Reemplaza los counters Prometheus (por-proceso, mueren con el proceso) por
persistencia en BD: la unica fuente de verdad comun entre los planos efimeros
del scheduler (GH Actions) y la API (Render). El healthcheck que corre en prod
cada 6h puede ahora leer los eventos y alertar via email.

Tabla append-only: el writer es unicamente observability/ops_events.py, que
nunca hace DDL y descarta silenciosamente si la tabla no existe.

Revision ID: v46_ops_events
Revises: v45_watchlist_items
Create Date: 2026-07-04
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v46_ops_events"
down_revision: str | Sequence[str] | None = "v45_watchlist_items"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ops_events (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            ts         TEXT NOT NULL DEFAULT (datetime('now','utc')),
            event_type TEXT NOT NULL,
            value      REAL,
            plane      TEXT,
            pid        INTEGER,
            detail     TEXT
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_ops_events_type_ts ON ops_events(event_type, ts)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_ops_events_type_ts")
    op.execute("DROP TABLE IF EXISTS ops_events")
