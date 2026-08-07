"""v73: índice concurrente sobre ``audit_log (created_at, id)``.

Revision ID: v73_audit_log_created_idx
Revises: v72_documentos_status_created_idx
Create Date: 2026-08-07

``db.audit.list_recent`` ordena por ``created_at DESC`` (con ``id`` como
desempate estable para paginación keyset), pero ``audit_log`` solo tenía índices
por ``user_key`` y ``action`` (v51): ese listado hacía un sort sobre toda la
tabla, que es append-only y crece sin límite. El índice compuesto permite el
scan hacia atrás sin ordenar.

Separado en su propia revisión y con ``autocommit_block`` por el mismo motivo que
v63/v66/v69: ``CREATE INDEX CONCURRENTLY`` no puede correr dentro de una
transacción, y así no bloquea las escrituras de auditoría mientras se construye.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from alembic import op

revision: str = "v73_audit_log_created_idx"
down_revision: str | None = "v72_documentos_status_created_idx"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_log_created_id "
            "ON audit_log (created_at, id)"
        )


def downgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_audit_log_created_id")
