"""Migración v33 — Columna password_hash en users.

Habilita el registro de usuarios locales con email + password (sign-up sin
Google OAuth). La columna es nullable: los usuarios creados vía OAuth no tienen
password_hash. Compatible con ``db.users.create_user`` y el endpoint
``POST /auth/register``.

El mismo cambio se aplica en el sistema legacy (``db/migrations.py`` v33) que es
el que ejecuta ``init_db`` en runtime y tests; esta revisión cubre el camino
canónico Alembic para bases de datos ya desplegadas.

Revision ID: v33_users_password_hash
Revises: v32_performance_indexes
Create Date: 2026-06-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "v33_users_password_hash"
down_revision: str | Sequence[str] | None = "v32_performance_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # No usar try/except: en Postgres un ADD COLUMN fallido deja la
    # transacción abortada para el resto de la migración. En modo offline
    # (--sql) no hay conexión real que introspeccionar.
    if context.is_offline_mode():
        op.add_column("users", sa.Column("password_hash", sa.Text, nullable=True))
        return
    insp = sa.inspect(op.get_bind())
    if "users" in insp.get_table_names() and "password_hash" not in {
        c["name"] for c in insp.get_columns("users")
    }:
        op.add_column("users", sa.Column("password_hash", sa.Text, nullable=True))


def downgrade() -> None:
    # SQLite no soporta DROP COLUMN antes de 3.35; omitimos rollback.
    pass
