"""Migracion v54 -- resincroniza secuencias de Postgres tras el bootstrap (ADR-016).

Esta migracion es DIALECT-GUARDED: solo hace algo en Postgres. En SQLite es
un no-op (AUTOINCREMENT no usa secuencias separadas, no hay desync posible).

Contexto: los datos reales de tablas como ``licitaciones``, ``adjudicaciones``,
``licitaciones_history``, ``contrato_eventos``, ``licitaciones_duplicados`` se
cargaron en Supabase preservando los ``id`` explicitos de origen (SQLite/Turso),
pero el bootstrap no reseteo la secuencia autoincremental asociada a cada
columna. Resultado: la secuencia arranca en 1 mientras la tabla ya tiene filas
con ids mas altos, y el primer INSERT nuevo choca con un id existente
(``UniqueViolation: duplicate key value ... already exists``) -- visto en
produccion en ``licitaciones_history`` (id=7) durante el pipeline diario.

En vez de parchear tabla por tabla, recorre TODAS las tablas de ``public`` con
una columna respaldada por secuencia (serial/identity) y la resincroniza a
``MAX(id) + 1``. Seguro de re-ejecutar: nunca deja la secuencia por debajo del
minimo necesario para evitar colisiones, sin importar su estado actual.

Revision ID: v54_resync_pg_sequences
Revises: v53_watchlist_cpv_missing_cols
Create Date: 2026-07-10
"""

from __future__ import annotations

from alembic import op

revision: str = "v54_resync_pg_sequences"
down_revision: str | None = "v53_watchlist_cpv_missing_cols"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return  # no-op en SQLite -- AUTOINCREMENT no tiene este problema

    op.execute(
        """
        DO $$
        DECLARE
            rec RECORD;
        BEGIN
            FOR rec IN
                SELECT
                    t.relname AS table_name,
                    a.attname AS column_name,
                    pg_get_serial_sequence(t.relname, a.attname) AS seq_name
                FROM pg_class t
                JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum > 0 AND NOT a.attisdropped
                WHERE t.relkind = 'r'
                  AND t.relnamespace = 'public'::regnamespace
                  AND pg_get_serial_sequence(t.relname, a.attname) IS NOT NULL
            LOOP
                EXECUTE format(
                    'SELECT setval(%L, COALESCE((SELECT MAX(%I) FROM public.%I), 0) + 1, false)',
                    rec.seq_name, rec.column_name, rec.table_name
                );
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    # No reversible con sentido: no hay forma segura de "recordar" el valor
    # previo de cada secuencia. No-op deliberado.
    pass
