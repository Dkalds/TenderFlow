"""v66: índices concurrentes para lotes (incluye las dos unique parciales).

Revision ID: v66_lotes_index_concurrent
Revises: v65_lotes
Create Date: 2026-07-31

Se separa del DDL de v65 porque ``autocommit_block`` confirma la transacción
anterior -- mismo patrón que v61->v63. Mantenerlo aislado evita una
migración parcialmente aplicada si la creación concurrente falla sobre el
histórico de ``adjudicaciones``.

Las dos unique parciales (``..._sin_lote`` / ``..._lic_lote_nif_importe``)
son la protección real que sustituye a la constraint que v65 borró; ver su
docstring para el razonamiento completo. Entre el commit de v65 y el de esta
revisión, ``adjudicaciones`` queda brevemente sin esa protección -- ventana
aceptada porque ambas se aplican en la misma pasada de
``alembic upgrade head``, sin tráfico de escritura de la aplicación de por
medio (ADR-012: un solo plano de orquestación).
"""

from __future__ import annotations

from alembic import op

revision: str = "v66_lotes_index_concurrent"
down_revision: str | None = "v65_lotes"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lotes_licitacion ON lotes (licitacion_id)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_adjudicaciones_lote "
            "ON adjudicaciones (lote_id)"
        )
        op.execute(
            "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "
            "uq_adjudicaciones_lic_nif_importe_sin_lote "
            "ON adjudicaciones (licitacion_id, nif, importe_adjudicado) "
            "WHERE lote_id IS NULL"
        )
        op.execute(
            "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "
            "uq_adjudicaciones_lic_lote_nif_importe "
            "ON adjudicaciones (licitacion_id, lote_id, nif, importe_adjudicado) "
            "WHERE lote_id IS NOT NULL"
        )


def downgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS uq_adjudicaciones_lic_lote_nif_importe")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS uq_adjudicaciones_lic_nif_importe_sin_lote")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_adjudicaciones_lote")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_lotes_licitacion")
