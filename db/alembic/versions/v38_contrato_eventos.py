"""Migración v38 — Eventos de contrato post-adjudicación (Fase 4).

Materializa el ciclo de vida del contrato como entidad consultable:
adjudicación, formalización, modificación de importe, prórroga y anulación,
derivados de ``licitaciones_history`` (services.contract_events).

``history_id`` traza cada evento a la fila de historial que lo originó; el
índice único parcial hace idempotente al derivador.

Idempotente (IF NOT EXISTS): db/schema.py crea la misma tabla en BDs
inicializadas vía init_db().

Revision ID: v38_contrato_eventos
Revises: v37_licitaciones_fuente
Create Date: 2026-06-11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v38_contrato_eventos"
down_revision: str | Sequence[str] | None = "v37_licitaciones_fuente"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS contrato_eventos (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            licitacion_id TEXT NOT NULL REFERENCES licitaciones(id_externo) ON DELETE CASCADE,
            tipo          TEXT NOT NULL CHECK(tipo IN
                          ('adjudicacion','formalizacion','modificacion','prorroga','anulacion','cambio_estado')),
            fecha         TEXT NOT NULL,
            campo         TEXT,
            valor_antes   TEXT,
            valor_despues TEXT,
            importe_delta REAL,
            detalle       TEXT,
            history_id    INTEGER,
            created_at    TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_eventos_lic ON contrato_eventos(licitacion_id, fecha)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_eventos_tipo ON contrato_eventos(tipo, fecha)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_eventos_dedupe "
        "ON contrato_eventos(history_id, tipo, COALESCE(campo, '')) "
        "WHERE history_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_eventos_dedupe")
    op.execute("DROP INDEX IF EXISTS idx_eventos_tipo")
    op.execute("DROP INDEX IF EXISTS idx_eventos_lic")
    op.execute("DROP TABLE IF EXISTS contrato_eventos")
