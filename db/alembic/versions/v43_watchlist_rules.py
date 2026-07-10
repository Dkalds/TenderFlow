"""Migración v43 — Watchlist por criterio (reglas keyword/CPV/importe/CCAA + alertas).

Reglas de seguimiento por usuario sobre criterios de búsqueda (no por empresa, ver
v36). El scheduler evaluará las reglas activas según su frecuencia y emitirá alertas
(job en increment posterior). Reemplaza el `localStorage` del frontend de
mi-watchlist por persistencia server-side (RFC ux-mi-watchlist; ADR-014 §2: el estado
de usuario es server-side, `localStorage` solo caché/migración one-shot).

Idempotente: db/schema.py (SCHEMA) crea la misma tabla en BDs inicializadas vía
init_db(), así que usa IF NOT EXISTS (mismo criterio que v34/v35/v36).

Revision ID: v43_watchlist_rules
Revises: v42_predicciones_retencion
Create Date: 2026-06-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v43_watchlist_rules"
down_revision: str | Sequence[str] | None = "v42_predicciones_retencion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        # AUTOINCREMENT/datetime('now') no son válidos en Postgres. La tabla
        # (incluida la columna email de v47) la crea
        # v55_pg_v27_v49_tables_backfill (DDL portable, más adelante).
        return
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS watchlist_rules (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            user_key         TEXT NOT NULL,
            user_id          INTEGER,
            nombre           TEXT,
            keyword          TEXT,
            cpv              TEXT,
            min_importe      REAL,
            ccaa             TEXT,
            frequency        TEXT NOT NULL DEFAULT 'daily',
            active           INTEGER NOT NULL DEFAULT 1,
            created_at       TEXT NOT NULL DEFAULT (datetime('now')),
            last_notified_at TEXT
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_wl_rules_user ON watchlist_rules(user_key)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wl_rules_active ON watchlist_rules(active, frequency)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_wl_rules_active")
    op.execute("DROP INDEX IF EXISTS idx_wl_rules_user")
    op.execute("DROP TABLE IF EXISTS watchlist_rules")
