"""Migración v36 — Watchlist por empresa (alertas de movimientos de competidores).

Permite vigilar empresas canónicas del maestro (v35): el scheduler detecta
nuevas adjudicaciones, entradas en territorio/CPV nuevo y vencimientos
próximos de contratos de las empresas vigiladas.

Idempotente: db/schema.py (SCHEMA) crea la misma tabla en BDs inicializadas
vía init_db(), así que usa IF NOT EXISTS (mismo criterio que v34/v35).

Revision ID: v36_watchlist_empresas
Revises: v35_empresa_master
Create Date: 2026-06-11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v36_watchlist_empresas"
down_revision: str | Sequence[str] | None = "v35_empresa_master"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        # AUTOINCREMENT/datetime('now') no son válidos en Postgres. La tabla
        # la crea v55_pg_v27_v49_tables_backfill (DDL portable, más adelante
        # en la cadena).
        return
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS watchlist_empresas (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            user_key         TEXT NOT NULL,
            empresa_id       INTEGER NOT NULL REFERENCES empresas(empresa_id) ON DELETE CASCADE,
            email            TEXT,
            frequency        TEXT NOT NULL DEFAULT 'daily',
            created_at       TEXT NOT NULL DEFAULT (datetime('now')),
            last_notified_at TEXT,
            UNIQUE(user_key, empresa_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_wl_emp_user ON watchlist_empresas(user_key)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_wl_emp_user")
    op.execute("DROP TABLE IF EXISTS watchlist_empresas")
