"""v70: repara la ausencia de ``idx_lic_fuente`` en Postgres.

Revision ID: v70_pg_missing_lic_fuente_index
Revises: v69_fecha_pub_d_index_concurrent
Create Date: 2026-08-04

DERIVA DE ESQUEMA. El índice sobre ``licitaciones(fuente)`` está declarado
dos veces en el linaje -- ``baseline002_pg_core_genesis.py:97``
(``op.create_index("idx_lic_fuente", ...)``) y ``v37_licitaciones_fuente.py:35``
y ``:47`` (``CREATE INDEX IF NOT EXISTS``) -- pero en la BD de producción
(Supabase, ADR-016) **no existe**, con ``alembic_version`` en
``v67_pg_short_tz_offset_repair``, o sea muy por delante de ambas. Se detectó
al perfilar el filtro por fuente de ``db.empresas.fetch_unlinked``:
``pg_indexes`` sobre ``licitaciones`` devuelve 11 índices y ninguno es
``idx_lic_fuente``, y el plan lo confirma::

    ->  Parallel Seq Scan on licitaciones l  (actual time=1435..8673 rows=692)
          Filter: (fuente = 'ted'::text)
          Rows Removed by Filter: 625464

8,6 s de recorrido secuencial sobre 1,25 M de filas por cada lote de
resolución. Con el índice, el mismo predicado son ~1400 filas por sonda.

Sigue el patrón de las otras reparaciones de deriva del linaje
(``v55_pg_v27_v49_tables_backfill``, ``v60_pg_missing_user_columns``,
``v67_pg_short_tz_offset_repair``): idempotente vía ``IF NOT EXISTS``, así que
es un no-op donde el índice sí se creó en su momento.

``CONCURRENTLY`` dentro de ``autocommit_block`` por el mismo motivo que v63,
v66 y v69: ``licitaciones`` es la tabla caliente del sistema y un
``CREATE INDEX`` normal la bloquea a escrituras mientras construye. Ver el
docstring de ``v66_lotes_index_concurrent``.

NOTA OPERATIVA: v68 (columna generada, reescribe ``licitaciones`` entera con
lock exclusivo) está entre el estado de producción y esta revisión, así que un
``alembic upgrade head`` a secas NO es la vía para desplegar este índice.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from alembic import op

revision: str = "v70_pg_missing_lic_fuente_index"
down_revision: str | None = "v69_fecha_pub_d_index_concurrent"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lic_fuente ON licitaciones (fuente)"
        )


def downgrade() -> None:
    # No se retira: el índice pertenece al linaje desde baseline002/v37 y esta
    # revisión sólo repara su ausencia. Quitarlo aquí volvería a abrir la
    # deriva que v70 cierra.
    pass
