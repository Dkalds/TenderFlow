"""Migracion v53 -- columnas faltantes en watchlist_cpv (Postgres).

Esta migracion es DIALECT-GUARDED: solo hace algo en Postgres. En SQLite es
un no-op (esas columnas ya existen ahi via ``db/migrations.py``).

Contexto: v51_pg_legacy_tables_backfill recreo ``watchlist_cpv`` en Postgres
con el shape de la migracion homegrown original (v2: id, user_key,
cpv_prefix, keyword, min_importe, ccaa, created_at), pero no incluyo las
columnas anadidas despues por el sistema casero via ALTER TABLE:
``last_notified_at`` (migracion 3), ``email`` (migracion 4), ``user_id``
(migracion 8) y ``frequency`` (migracion 15). Resultado: cualquier query de
``db/watchlist.py`` que seleccione esas columnas falla con
``UndefinedColumn`` en Postgres pese a que ``alembic current`` reporta head.

``ADD COLUMN IF NOT EXISTS`` (nativo de Postgres) en vez de ``op.add_column``
para que la migracion sea segura de re-ejecutar aunque alguna columna ya
exista por un backfill manual previo.

Revision ID: v53_watchlist_cpv_missing_columns
Revises: v52_rls_lockdown
Create Date: 2026-07-10
"""

from __future__ import annotations

from alembic import op

revision: str = "v53_watchlist_cpv_missing_columns"
down_revision: str | None = "v52_rls_lockdown"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return  # no-op en SQLite -- columnas ya existen via db/migrations.py

    op.execute("ALTER TABLE watchlist_cpv ADD COLUMN IF NOT EXISTS last_notified_at TEXT")
    op.execute("ALTER TABLE watchlist_cpv ADD COLUMN IF NOT EXISTS email TEXT")
    op.execute(
        "ALTER TABLE watchlist_cpv ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id)"
    )
    op.execute(
        "ALTER TABLE watchlist_cpv ADD COLUMN IF NOT EXISTS frequency TEXT NOT NULL DEFAULT 'daily'"
    )
    op.create_index("idx_wl_user_id", "watchlist_cpv", ["user_id"], if_not_exists=True)


def downgrade() -> None:
    if not _is_postgres():
        return  # no-op en SQLite

    op.drop_index("idx_wl_user_id", table_name="watchlist_cpv", if_exists=True)
    op.execute("ALTER TABLE watchlist_cpv DROP COLUMN IF EXISTS frequency")
    op.execute("ALTER TABLE watchlist_cpv DROP COLUMN IF EXISTS user_id")
    op.execute("ALTER TABLE watchlist_cpv DROP COLUMN IF EXISTS email")
    op.execute("ALTER TABLE watchlist_cpv DROP COLUMN IF EXISTS last_notified_at")
