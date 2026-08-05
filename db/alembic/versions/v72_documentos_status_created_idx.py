"""v72: índice concurrente ``documentos(status, created_at)``.

Revision ID: v72_documentos_status_created_idx
Revises: v71_licitacion_tecnologia_pliego
Create Date: 2026-08-04

``DocumentosRepository.list_pendientes`` pasa a un ORDER BY compuesto
(prioridad tech-relevante, luego created_at) para priorizar la cola de fetch
sobre el backlog de ~43.9k documentos. Se separa en su propia revisión
--mismo patrón v61->v63, v65->v66-- porque ``autocommit_block`` confirma la
transacción anterior y CONCURRENTLY no puede correr dentro de una transacción
abierta por alembic.
"""

from __future__ import annotations

from alembic import op

revision: str = "v72_documentos_status_created_idx"
down_revision: str | None = "v71_licitacion_tecnologia_pliego"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_documentos_status_created "
            "ON documentos (status, created_at)"
        )


def downgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_documentos_status_created")
