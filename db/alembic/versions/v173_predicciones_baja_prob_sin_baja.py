"""v173: ``predicciones_baja.prob_sin_baja``, la probabilidad de adjudicar sin baja.

El modelo de baja gana un clasificador auxiliar (``services.ml.baja_model``):
P(baja < 0,05 %), es decir, que se adjudique al presupuesto. En PLACSP es el
28 % de los pares del dataset, casi siempre con un único licitador, y es una
señal de producto por sí misma («probabilidad de que nadie más se presente»).

Columna NULLable y sin DEFAULT: ``ADD COLUMN`` es solo de catálogo (la lección
de v68). NULL significa «no hay probabilidad que dar»: la fila la sirvió el
baseline, el artefacto es anterior al clasificador o este no batió a la
prevalencia en Brier. La escriben el batch agregado y el por lote.

DIALECT-GUARDED: solo actúa en Postgres.

Revision ID: v173_predicciones_baja_prob_sin_baja
Revises: v172_empresas_busqueda_trgm
Create Date: 2026-11-07
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v173_predicciones_baja_prob_sin_baja"
down_revision: str | Sequence[str] | None = "v172_empresas_busqueda_trgm"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        "ALTER TABLE predicciones_baja ADD COLUMN IF NOT EXISTS prob_sin_baja DOUBLE PRECISION"
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("ALTER TABLE predicciones_baja DROP COLUMN IF EXISTS prob_sin_baja")
