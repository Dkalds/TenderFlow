"""v77: índice concurrente sobre ``licitaciones.fecha_extraccion``.

Revision ID: v77_lic_fecha_extraccion_index
Revises: v76_radar_dismissals
Create Date: 2026-08-10

``LicitacionRepository.get_last_extraction_date`` resuelve
``SELECT MAX(fecha_extraccion) FROM licitaciones`` y era la tercera consulta más
cara de producción: sin índice, el planner solo puede recorrer las 1,64 M filas
de la tabla (972 MB de heap) para quedarse con un único valor.

Medido en ``pg_stat_statements`` el 2026-08-10: 134 llamadas, 16,6 s de media,
93 s de pico y 2.228 s acumulados. Lo llama ``/api/v1/meta/last-extraction``, que
el frontend pide en cada carga de página, así que cada visita arrancaba un
escaneo completo y retenía una conexión del pool (12 slots) durante decenas de
segundos — de ahí los ``couldn't get a connection after 30.00 sec`` que acababan
en 500 y 502 para el resto de endpoints.

Con el btree, ``MAX()`` pasa a ser un index scan hacia atrás que se detiene en la
primera fila viva.

Va por separado y con ``CONCURRENTLY`` por el mismo motivo que v66 y v69: sobre
una tabla de este tamaño un ``CREATE INDEX`` normal bloquea las escrituras del
scraper durante toda la construcción.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v77_lic_fecha_extraccion_index"
down_revision: str | Sequence[str] | None = "v76_radar_dismissals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lic_fecha_extraccion "
            "ON licitaciones (fecha_extraccion)"
        )


def downgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_lic_fecha_extraccion")
