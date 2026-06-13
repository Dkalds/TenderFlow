"""Migración v29 — Tablas materializadas para agregados.

No-op: las tablas ``mat_clusters`` y ``mat_top_empresas_ccaa`` ya fueron
creadas por la migración Alembic v20 (``v20_mat_aggregates``). No se
requiere ninguna acción.

Revision ID: v29_mat_aggregates
Revises: v28_api_key_tiers
Create Date: 2026-06-02
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "v29_mat_aggregates"
down_revision: str | Sequence[str] | None = "v28_api_key_tiers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
