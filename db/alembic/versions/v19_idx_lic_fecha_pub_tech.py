"""Migración v19 — Índice parcial fecha_publicacion para licitaciones clasificadas.

El hot path ``_load_raw()`` en el dashboard filtra por
``WHERE tecnologia IS NOT NULL AND tecnologia != ''``
y ordena por ``fecha_publicacion DESC``. Este índice parcial cubre
exactamente esa consulta, acelerando la carga inicial del dataset.

Revision ID: v19_idx_lic_fecha_pub_tech
Revises: v18_history_yearly_views
Create Date: 2026-05-17
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v19_idx_lic_fecha_pub_tech"
down_revision: str | Sequence[str] | None = "v18_history_yearly_views"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_lic_fecha_pub_tech "
        "ON licitaciones(fecha_publicacion DESC) "
        "WHERE tecnologia IS NOT NULL AND tecnologia != ''"
    )


def downgrade() -> None:
    op.drop_index("idx_lic_fecha_pub_tech", table_name="licitaciones")
