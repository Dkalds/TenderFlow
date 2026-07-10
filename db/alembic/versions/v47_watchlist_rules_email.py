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

import sqlalchemy as sa
from alembic import context, op

revision: str = "v47_watchlist_rules_email"
down_revision: str | Sequence[str] | None = "v46_ops_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # watchlist_rules no existe todavía en un bootstrap Postgres fresco (v43
    # se salta en Postgres; la crea v55_pg_v27_v49_tables_backfill, mucho más
    # adelante en la cadena, ya con la columna email incluida). No usar
    # try/except: en Postgres un ADD COLUMN fallido deja la transacción
    # abortada para el resto de la migración. En modo offline (--sql) no hay
    # conexión real que introspeccionar.
    if context.is_offline_mode():
        op.execute("ALTER TABLE watchlist_rules ADD COLUMN email TEXT")
        return
    insp = sa.inspect(op.get_bind())
    if "watchlist_rules" not in insp.get_table_names():
        return
    if "email" not in {c["name"] for c in insp.get_columns("watchlist_rules")}:
        op.execute("ALTER TABLE watchlist_rules ADD COLUMN email TEXT")


def downgrade() -> None:
    # SQLite no soporta DROP COLUMN antes de 3.35; usar recreacion de tabla
    # en entornos que lo requieran. En produccion esta migracion es permanente.
    pass
