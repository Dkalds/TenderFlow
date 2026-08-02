"""v69: índice concurrente sobre ``licitaciones.fecha_pub_d``.

Revision ID: v69_fecha_pub_d_index_concurrent
Revises: v68_fecha_pub_date_generated
Create Date: 2026-08-02

Separado de v68 por el mismo motivo que v63 y v66: ``autocommit_block``
confirma la transacción anterior antes de construir el índice sin bloquear
escrituras. Ver docstring de v66_lotes_index_concurrent.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from alembic import op

revision: str = "v69_fecha_pub_d_index_concurrent"
down_revision: str | None = "v68_fecha_pub_date_generated"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lic_fecha_pub_d "
            "ON licitaciones (fecha_pub_d)"
        )


def downgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_lic_fecha_pub_d")
