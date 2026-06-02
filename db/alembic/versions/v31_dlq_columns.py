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
from alembic import op

revision: str = "v31_dlq_columns"
down_revision: str | Sequence[str] | None = "v30_ml_tecnologias_multilabel"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    try:
        op.add_column("failed_extractions", sa.Column("last_attempt_at", sa.Text(), nullable=True))
    except Exception:
        pass
    try:
        op.add_column("failed_extractions", sa.Column("exhausted_at", sa.Text(), nullable=True))
    except Exception:
        pass
    try:
        op.execute(
            "UPDATE failed_extractions "
            "SET last_attempt_at = created_at "
            "WHERE last_attempt_at IS NULL"
        )
    except Exception:
        pass
    try:
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_fail_exhausted "
            "ON failed_extractions(exhausted_at) WHERE exhausted_at IS NOT NULL"
        )
    except Exception:
        pass


def downgrade() -> None:
    pass
