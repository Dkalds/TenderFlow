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

import sqlalchemy as sa
from alembic import context, op

revision: str = "v37_licitaciones_fuente"
down_revision: str | Sequence[str] | None = "v36_watchlist_empresas"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if context.is_offline_mode():
        # En modo offline (alembic --sql) no se puede introspeccionar; el script
        # se aplica sobre una BD real con licitaciones ya presente, así que
        # emitimos el DDL directamente.
        op.execute("ALTER TABLE licitaciones ADD COLUMN fuente TEXT NOT NULL DEFAULT 'placsp'")
        op.execute("UPDATE licitaciones SET fuente = 'placsp' WHERE fuente IS NULL OR fuente = ''")
        op.execute("CREATE INDEX IF NOT EXISTS idx_lic_fuente ON licitaciones(fuente)")
        return

    # No usar sqlite_master/PRAGMA (no existen en Postgres): usar el
    # inspector de SQLAlchemy, portable entre dialectos.
    insp = sa.inspect(op.get_bind())
    if "licitaciones" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("licitaciones")}
    if "fuente" not in cols:
        op.execute("ALTER TABLE licitaciones ADD COLUMN fuente TEXT NOT NULL DEFAULT 'placsp'")
    op.execute("UPDATE licitaciones SET fuente = 'placsp' WHERE fuente IS NULL OR fuente = ''")
    op.execute("CREATE INDEX IF NOT EXISTS idx_lic_fuente ON licitaciones(fuente)")


def downgrade() -> None:
    # ADD COLUMN no es reversible en SQLite < 3.35; solo retiramos el índice.
    op.execute("DROP INDEX IF EXISTS idx_lic_fuente")
