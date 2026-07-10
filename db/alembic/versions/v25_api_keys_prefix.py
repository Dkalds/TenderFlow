"""Migración v25 — Columna prefix en api_keys para identificación visual.

Añade la columna ``prefix`` a la tabla ``api_keys`` para mostrar
los primeros caracteres de la clave (ej. ``sk_pro_a1b2...``) en la UI
sin exponer el hash completo.

La columna ``expires_at`` ya fue añadida por la migración Alembic v15.
Aquí se añade únicamente ``prefix``.

Revision ID: v25_api_keys_prefix
Revises: v24_cursor_composite_index
Create Date: 2026-06-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "v25_api_keys_prefix"
down_revision: str | Sequence[str] | None = "v24_cursor_composite_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # No usar try/except: en Postgres un ADD COLUMN fallido deja la
    # transacción abortada para el resto de la migración. En modo offline
    # (--sql) no hay conexión real que introspeccionar.
    if context.is_offline_mode():
        op.add_column("api_keys", sa.Column("prefix", sa.Text(), nullable=True))
        return
    insp = sa.inspect(op.get_bind())
    if "api_keys" in insp.get_table_names() and "prefix" not in {
        c["name"] for c in insp.get_columns("api_keys")
    }:
        op.add_column("api_keys", sa.Column("prefix", sa.Text(), nullable=True))


def downgrade() -> None:
    # SQLite < 3.35 no soporta DROP COLUMN en ALTER TABLE.
    # Para SQLite 3.35+ se podría usar op.drop_column, pero no es seguro
    # asumir la versión. Omitimos downgrade.
    pass
