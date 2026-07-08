"""Migración v45 — Watchlist items (favoritos de licitaciones individuales).

A diferencia de v43 (``watchlist_rules``, seguimiento por criterio) y v36
(``watchlist_empresas``, seguimiento por empresa), esta tabla cubre el caso más
simple: marcar una licitación concreta (``id_externo``) como favorita. Reemplaza
el ``localStorage`` (`detalle_watchlist`) del frontend por persistencia
server-side (RFC ux-mi-watchlist F5; ADR-014 §2: el estado de usuario es
server-side, ``localStorage`` solo caché/migración one-shot).

Sin FK dura a ``licitaciones.id_externo`` (mismo criterio que v43: las
licitaciones pueden expirar/purgarse sin que el favorito deba desaparecer en
cascada; el join en el repositorio ya tolera ausencia de la licitación).

Idempotente: db/schema.py (SCHEMA) crea la misma tabla en BDs inicializadas vía
init_db(), así que usa IF NOT EXISTS (mismo criterio que v34/v35/v36/v43).

Revision ID: v45_watchlist_items
Revises: v44_ml_feedback_tecnologia
Create Date: 2026-07-03
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v45_watchlist_items"
down_revision: str | Sequence[str] | None = "v44_ml_feedback_tecnologia"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS watchlist_items (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_key    TEXT NOT NULL,
            user_id     INTEGER,
            id_externo  TEXT NOT NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(user_key, id_externo)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_wl_items_user ON watchlist_items(user_key)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_wl_items_user")
    op.execute("DROP TABLE IF EXISTS watchlist_items")
