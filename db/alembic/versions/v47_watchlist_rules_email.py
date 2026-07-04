"""Migracion v47 -- columna email en watchlist_rules.

Permite asociar un email de entrega a cada regla de watchlist en el momento
de crearla (tomado del contexto de sesion OAuth). Las reglas creadas con
API key quedan con email=NULL y solo reciben notificaciones in-app.

No rompe nada existente: columna nullable, la logica anterior ignora el campo.

Revision ID: v47_watchlist_rules_email
Revises: v46_ops_events
Create Date: 2026-07-05
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v47_watchlist_rules_email"
down_revision: str | Sequence[str] | None = "v46_ops_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE watchlist_rules ADD COLUMN email TEXT")


def downgrade() -> None:
    # SQLite no soporta DROP COLUMN antes de 3.35; usar recreacion de tabla
    # en entornos que lo requieran. En produccion esta migracion es permanente.
    pass
