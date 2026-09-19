"""v134: índices concurrentes sobre las fechas sombra de ``licitaciones`` (T2).

Revision ID: v134_nucleo_tipado_indices
Revises: v133_nucleo_tipado_sombra
Create Date: 2026-09-18

Separado de ``v133`` por el mismo motivo que ``v69`` de ``v68``:
``autocommit_block`` confirma la transacción anterior antes de construir el
índice sin bloquear escrituras.

**Se aplica después del backfill, no junto a ``v133``.** Mientras el backfill
reescribe las dos columnas fila a fila, un índice sobre ellas convierte cada
``UPDATE`` en no-HOT (hay que tocar el índice además del heap) y multiplica el
WAL de la ventana. El runbook (``docs/runbooks/nucleo-tipado-ventana.md``) lo
ordena así: ``alembic upgrade v133_nucleo_tipado_sombra`` → despliegue con la
escritura dual → backfill verificado → ``alembic upgrade v134_nucleo_tipado_indices``.
Aplicarla antes no rompe nada; sólo encarece el backfill.

``importe_num`` y ``duracion_valor_num`` no llevan índice: el plan (§6 T2) sólo
pide los dos de fecha, y el filtro de importe del listado se resuelve hoy sobre
``idx_lic_importe``. Si el cambio de lecturas lo pide, va en otra revisión.

Nombres ``idx_lic_*`` y no los ``ix_lic_*`` del borrador del plan: es la
convención de todos los índices de ``licitaciones`` (ver
``docs/database-schema.md``).

**Si un ``CREATE INDEX CONCURRENTLY`` falla a medias deja un índice
``INVALID`` detrás**, y el ``IF NOT EXISTS`` de un reintento lo daría por
bueno. El runbook comprueba ``pg_index.indisvalid`` después de aplicar.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from alembic import op

revision: str = "v134_nucleo_tipado_indices"
down_revision: str | None = "v133_nucleo_tipado_sombra"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lic_fecha_publicacion_ts "
            "ON licitaciones (fecha_publicacion_ts)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lic_fecha_limite_ts "
            "ON licitaciones (fecha_limite_ts)"
        )


def downgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_lic_fecha_limite_ts")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_lic_fecha_publicacion_ts")
