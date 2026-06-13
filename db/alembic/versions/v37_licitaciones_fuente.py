"""Migración v37 — Columna ``fuente`` en licitaciones (ADR-009 multi-fuente).

Discriminador explícito de la fuente de ingesta ('placsp', 'ted', …) con
backfill a 'placsp' para todas las filas existentes. Las fuentes nuevas
namespacean además su id_externo como "{fuente}:{id_natural}".

Idempotente (guard PRAGMA): db/schema.py añade la misma columna en BDs
inicializadas vía init_db().

Revision ID: v37_licitaciones_fuente
Revises: v36_watchlist_empresas
Create Date: 2026-06-11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v37_licitaciones_fuente"
down_revision: str | Sequence[str] | None = "v36_watchlist_empresas"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    table_exists = bind.exec_driver_sql(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='licitaciones'"
    ).fetchone()
    if not table_exists:
        return
    cols = {row[1] for row in bind.exec_driver_sql("PRAGMA table_info(licitaciones)").fetchall()}
    if "fuente" not in cols:
        op.execute("ALTER TABLE licitaciones ADD COLUMN fuente TEXT NOT NULL DEFAULT 'placsp'")
    op.execute("UPDATE licitaciones SET fuente = 'placsp' WHERE fuente IS NULL OR fuente = ''")
    op.execute("CREATE INDEX IF NOT EXISTS idx_lic_fuente ON licitaciones(fuente)")


def downgrade() -> None:
    # ADD COLUMN no es reversible en SQLite < 3.35; solo retiramos el índice.
    op.execute("DROP INDEX IF EXISTS idx_lic_fuente")
