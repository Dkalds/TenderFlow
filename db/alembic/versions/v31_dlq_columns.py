"""Migración v31 — Columnas de DLQ en failed_extractions.

Añade columnas de gestión del dead-letter queue a ``failed_extractions``
para soportar backoff exponencial y tracking de agotamiento de reintentos.

- ``last_attempt_at`` — timestamp del último reintento; usado para
  calcular el backoff. Se inicializa con ``created_at`` para entradas
  existentes.
- ``exhausted_at`` — timestamp en que la entrada alcanzó ``max_retries``;
  NULL mientras esté activa.

Revision ID: v31_dlq_columns
Revises: v30_ml_tecnologias_multilabel
Create Date: 2026-06-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "v31_dlq_columns"
down_revision: str | Sequence[str] | None = "v30_ml_tecnologias_multilabel"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # failed_extractions no existe todavía en un bootstrap Postgres fresco
    # (la crea v51_pg_legacy_tables_backfill, mucho más adelante en la
    # cadena) -- no usar try/except: en Postgres un statement fallido deja
    # la transacción abortada para el resto de la migración. En modo
    # offline (--sql) no hay conexión real que introspeccionar.
    if context.is_offline_mode():
        op.add_column("failed_extractions", sa.Column("last_attempt_at", sa.Text(), nullable=True))
        op.add_column("failed_extractions", sa.Column("exhausted_at", sa.Text(), nullable=True))
        op.execute(
            "UPDATE failed_extractions "
            "SET last_attempt_at = created_at "
            "WHERE last_attempt_at IS NULL"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_fail_exhausted "
            "ON failed_extractions(exhausted_at) WHERE exhausted_at IS NOT NULL"
        )
        return
    insp = sa.inspect(op.get_bind())
    if "failed_extractions" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("failed_extractions")}
    if "last_attempt_at" not in cols:
        op.add_column("failed_extractions", sa.Column("last_attempt_at", sa.Text(), nullable=True))
    if "exhausted_at" not in cols:
        op.add_column("failed_extractions", sa.Column("exhausted_at", sa.Text(), nullable=True))
    op.execute(
        "UPDATE failed_extractions SET last_attempt_at = created_at WHERE last_attempt_at IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_fail_exhausted "
        "ON failed_extractions(exhausted_at) WHERE exhausted_at IS NOT NULL"
    )


def downgrade() -> None:
    pass
