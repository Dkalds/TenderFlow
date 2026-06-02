"""Migración v24 — Índice compuesto para cursor pagination.

No-op: el índice ``idx_lic_cursor`` sobre
``(fecha_publicacion DESC, id_externo)`` ya fue creado en la migración
Alembic v21 (``v21_missing_indexes``). No se requiere ninguna acción.

Revision ID: v24_cursor_composite_index
Revises: v23_ml_proba_column
Create Date: 2026-06-02
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "v24_cursor_composite_index"
down_revision: str | Sequence[str] | None = "v23_ml_proba_column"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
