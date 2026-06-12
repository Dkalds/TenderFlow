"""Migración v41 — Predicciones de baja ganadora (Fase 6.1, RFC 20260611-2).

Serving batch del modelo cuantílico p10/p50/p90: el scoring nocturno escribe
aquí y la API/frontend solo leen. PK natural = licitacion_id con
INSERT OR REPLACE (idempotencia del batch, invariante §3.2). Cada fila lleva
``model_version`` y ``computed_at`` para trazabilidad (anti-"número mágico").

Idempotente (IF NOT EXISTS): db/schema.py crea la misma tabla en BDs
inicializadas vía init_db().

Revision ID: v41_predicciones_baja
Revises: v40_resoluciones_recurso
Create Date: 2026-06-11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v41_predicciones_baja"
down_revision: str | Sequence[str] | None = "v40_resoluciones_recurso"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS predicciones_baja (
            licitacion_id TEXT PRIMARY KEY
                          REFERENCES licitaciones(id_externo) ON DELETE CASCADE,
            p10           REAL NOT NULL,
            p50           REAL NOT NULL,
            p90           REAL NOT NULL,
            model_version INTEGER,
            computed_at   TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_pred_baja_computed ON predicciones_baja(computed_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_pred_baja_computed")
    op.execute("DROP TABLE IF EXISTS predicciones_baja")
