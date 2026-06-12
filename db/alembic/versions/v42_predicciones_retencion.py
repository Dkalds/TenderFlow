"""Migración v42 — Predicciones de retención de renovaciones (Fase 6.2).

"Riesgo de cambio de manos" del incumbente en contratos que vencen: scoring
batch del clasificador calibrado de retención. PK natural = licitacion_id
(contrato que vence) + INSERT OR REPLACE (idempotencia §3.2); cada fila
lleva ``model_version`` y ``computed_at`` (trazabilidad).

Idempotente (IF NOT EXISTS): db/schema.py crea la misma tabla en BDs
inicializadas vía init_db().

Revision ID: v42_predicciones_retencion
Revises: v41_predicciones_baja
Create Date: 2026-06-11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v42_predicciones_retencion"
down_revision: str | Sequence[str] | None = "v41_predicciones_baja"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS predicciones_retencion (
            licitacion_id  TEXT PRIMARY KEY
                           REFERENCES licitaciones(id_externo) ON DELETE CASCADE,
            empresa_id     INTEGER REFERENCES empresas(empresa_id),
            prob_retencion REAL NOT NULL,
            riesgo_cambio  REAL NOT NULL,
            model_version  INTEGER,
            computed_at    TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_pred_ret_riesgo "
        "ON predicciones_retencion(riesgo_cambio DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_pred_ret_riesgo")
    op.execute("DROP TABLE IF EXISTS predicciones_retencion")
