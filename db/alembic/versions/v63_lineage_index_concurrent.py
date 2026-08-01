"""v63: índice concurrente del universo analítico.

Revision ID: v63_lineage_index_concurrent
Revises: v62_product_truth_and_tender_facts
Create Date: 2026-07-30

Se separa del DDL de v61 porque ``autocommit_block`` confirma la transacción
anterior. Mantenerlo aislado evita una migración parcialmente aplicada si la
creación concurrente falla sobre el histórico de ``licitaciones``.
"""

from __future__ import annotations

from alembic import op

revision: str = "v63_lineage_index_concurrent"
down_revision: str | None = "v62_product_truth_and_tender_facts"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "idx_licitaciones_analysis_lineage "
            "ON licitaciones (analysis_universe, filter_version)"
        )


def downgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_licitaciones_analysis_lineage")
