"""v160: índice concurrente sobre ``licitaciones.fecha_extraccion_ts``.

Revision ID: v160_fechas_ts_indices
Revises: v159_fechas_ts_sombra
Create Date: 2026-10-25

Separado de ``v159`` por el mismo motivo que ``v134`` de ``v133``:
``autocommit_block`` confirma la transacción anterior antes de construir el
índice sin bloquear escrituras, y el índice se construye **después** del
backfill (``docs/runbooks/fechas-ts-ventana.md``): mientras el backfill
reescribe la columna fila a fila, un índice sobre ella vuelve no-HOT cada
``UPDATE`` y multiplica el WAL. Aplicarla antes no rompe nada; solo encarece la
ventana.

Un solo índice, el único que una lectura necesita: con ``FECHAS_TS_LECTURA``
encendido, ``LicitacionRepository.get_last_extraction_date`` pide
``MAX(fecha_extraccion_ts)``, que es lo que ``v77`` resolvió para la columna de
texto. Sin este btree esa consulta vuelve a ser el seq scan de 1,6 M filas que
llegó a retener conexiones del pool durante decenas de segundos, así que **el
flag no se enciende antes de esta revisión**.

Las demás lecturas duales (novedades, historial, notificaciones) filtran antes
por una clave con índice propio (``id_externo``, el usuario, la organización) y
ordenan unas pocas filas por ``COALESCE(<col>_ts, …)``, que ningún índice sobre
la sombra desnuda serviría. Los índices de texto que hoy existen sobre estas
fechas (``idx_adj_fecha``, ``idx_hist_externo``, ``idx_documentos_status_created``)
se replican sobre la sombra cuando una lectura los pida, no antes: un índice
sin lector es WAL y espacio a cambio de nada.

**Si un ``CREATE INDEX CONCURRENTLY`` falla a medias deja un índice
``INVALID``**, y el ``IF NOT EXISTS`` de un reintento lo daría por bueno. El
runbook comprueba ``pg_index.indisvalid`` después de aplicar.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from alembic import op

revision: str = "v160_fechas_ts_indices"
down_revision: str | None = "v159_fechas_ts_sombra"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lic_fecha_extraccion_ts "
            "ON licitaciones (fecha_extraccion_ts)"
        )


def downgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_lic_fecha_extraccion_ts")
