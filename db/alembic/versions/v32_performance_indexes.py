"""Migración v32 — Índices de rendimiento para queries frecuentes.

Añade índices de rendimiento que cubren hot paths identificados tras
análisis de rendimiento en producción:

- ``idx_lic_ml_proba`` — filtrado y ordenación por probabilidad ML en
  el dashboard (licitaciones con mayor probabilidad de tecnología).
- ``idx_adj_nombre_importe`` — búsqueda de adjudicaciones por nombre de
  empresa + rango de importe (top empresas dashboard).
- ``idx_adj_ccaa_nombre`` — agregación de adjudicaciones por CCAA y
  empresa (mapa de calor geográfico).

``idx_lic_tecnologia`` ya fue creado en la migración Alembic v21 y
no se repite aquí.

Revision ID: v32_performance_indexes
Revises: v31_dlq_columns
Create Date: 2026-06-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v32_performance_indexes"
down_revision: str | Sequence[str] | None = "v31_dlq_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS idx_lic_ml_proba ON licitaciones(ml_proba)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_adj_nombre_importe "
        "ON adjudicaciones(nombre, importe_adjudicado)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_adj_ccaa_nombre "
        "ON adjudicaciones(ccaa, nombre)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_adj_ccaa_nombre")
    op.execute("DROP INDEX IF EXISTS idx_adj_nombre_importe")
    op.execute("DROP INDEX IF EXISTS idx_lic_ml_proba")
