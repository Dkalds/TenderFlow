"""Migracion v57 -- columna users.is_admin (Postgres).

Reconcilia un drift de schema: la tabla ``public.users`` en Supabase se creo
sin la columna ``is_admin`` (la baseline PG ``baseline002_pg_core_genesis`` no
la incluye y ninguna revision posterior la anadio), mientras que el codigo de
la app (``db/users.py``: ``is_admin()``, ``set_admin()``, ``list_users()``) y
el schema canonico SQLite (``db/migrations.py`` migracion #10
``_apply_v10_is_admin``) si la esperan. Sin esta columna, ``POST /auth/login``
devuelve 500 al construir ``UserInfo(is_admin=...)``.

DIALECT-GUARDED: solo actua en Postgres (patron post-cutover desde v50; el
equivalente SQLite vive en ``db/schema.py::SCHEMA`` / ``db/migrations.py``).

Idempotente: ``ADD COLUMN IF NOT EXISTS`` -- seguro de re-aplicar.

Revision ID: v57_pg_users_is_admin
Revises: v56_pg_documentos_pgvector
Create Date: 2026-07-16
"""

from __future__ import annotations

from alembic import op

revision: str = "v57_pg_users_is_admin"
down_revision: str | None = "v56_pg_documentos_pgvector"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


_ADD_IS_ADMIN = "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin INTEGER NOT NULL DEFAULT 0"
_DROP_IS_ADMIN = "ALTER TABLE users DROP COLUMN IF EXISTS is_admin"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.execute(_ADD_IS_ADMIN)


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute(_DROP_IS_ADMIN)
