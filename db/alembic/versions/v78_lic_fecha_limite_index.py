"""v78: índice concurrente sobre ``licitaciones.fecha_limite``.

Revision ID: v78_lic_fecha_limite_index
Revises: v77_lic_fecha_extraccion_index
Create Date: 2026-08-11

``fecha_limite`` decide qué es una oportunidad viva —el universo del Radar
(``AggregateRepository.scoring_candidates``) y los contadores "para hoy" de
``overview_para_hoy`` (``calientes_hoy``, ``vencen_48h``) filtran por ella— y
era la única de esas columnas sin índice: ``fecha_publicacion``,
``fecha_extraccion``, ``estado``, ``ccaa``, ``cpv`` y ``tecnologia`` ya lo
tenían.

Medido en producción el 2026-08-11 sobre la consulta del Radar ya acotada
(estado no terminal + plazo por vencer): Parallel Seq Scan, 124.454 buffers y
6.794 ms para devolver 1.643 filas de 1.640.915. El btree convierte eso en un
index scan sobre el rango ``>= hoy``, que es el 0,1% de la tabla.

El comentario de ``_iso_guard`` ya daba por hecho este índice ("sin renunciar al
índice btree de la columna"): el rango lexicográfico se eligió precisamente para
ser sargable. Faltaba el índice.

Va por separado y con ``CONCURRENTLY`` por el mismo motivo que v66, v69 y v77:
sobre una tabla de este tamaño un ``CREATE INDEX`` normal bloquea las escrituras
del scraper durante toda la construcción.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v78_lic_fecha_limite_index"
down_revision: str | Sequence[str] | None = "v77_lic_fecha_extraccion_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lic_fecha_limite "
            "ON licitaciones (fecha_limite)"
        )


def downgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_lic_fecha_limite")
