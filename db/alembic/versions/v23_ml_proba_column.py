"""Migración v23 — Columna ml_proba en licitaciones.

No-op: la columna ``ml_proba`` ya está presente en la definición batch
de la migración v22 (ver ``_lic_pre`` en v22) y en ``db/models.py``.
Para bases de datos que hayan ejecutado el pipeline completo v1-v22 por
Alembic, esta columna ya existe. No requiere ninguna acción.

Revision ID: v23_ml_proba_column
Revises: v22_fk_cascade_date_checks
Create Date: 2026-06-02
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "v23_ml_proba_column"
down_revision: str | Sequence[str] | None = "v22_fk_cascade_date_checks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
