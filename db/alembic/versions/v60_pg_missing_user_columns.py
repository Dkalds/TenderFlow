"""Migracion v60 -- columnas users.deactivated_at y api_keys.scopes (Postgres).

Mismo drift de schema que corrigio v57 con ``users.is_admin``: dos columnas que
el sistema legado de migraciones (``db/migrations.py``, camino SQLite) anade
mediante ``ALTER TABLE ADD COLUMN`` programatico, y que nunca viajaron al
schema Postgres al portarlo (ADR-016). El codigo de la app si las espera:

* ``users.deactivated_at`` (migracion legacy #35, soft-delete) -- la usan ocho
  sentencias de ``db/users.py``: ``get_user_by_email``, ``get_user_by_oauth``,
  ``list_users``, ``deactivate_user``, ``reactivate_user`` y el borrado GDPR.
  Sin la columna, listar usuarios o desactivar una cuenta devuelve 500.

* ``api_keys.scopes`` (migracion legacy #40) -- la usa
  ``db/repositories/api_keys.py`` al validar y listar claves.

Detectado al migrar la suite de tests al motor real (ADR-018): 34 tests
fallaban con ``column "deactivated_at" does not exist`` y 4 con ``column
"scopes" does not exist``, contra un Postgres con ``alembic upgrade head``
aplicado. Sobre SQLite pasaban todos, porque ahi las columnas si existen.

Idempotente: ``ADD COLUMN IF NOT EXISTS`` -- seguro de re-aplicar.

DIALECT-GUARDED: solo actua en Postgres; en SQLite las columnas ya existen.

Revision ID: v60_pg_missing_user_columns
Revises: v59_pg_date_format_checks
Create Date: 2026-07-26
"""

from __future__ import annotations

from alembic import op

revision: str = "v60_pg_missing_user_columns"
down_revision: str | None = "v59_pg_date_format_checks"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

# (tabla, columna, definicion) -- tipos espejo de db/migrations.py
_COLUMNS: list[tuple[str, str, str]] = [
    # NULL = activo; TEXT ISO = timestamp de desactivacion (migracion legacy #35).
    ("users", "deactivated_at", "TEXT"),
    # '*' = todos los scopes, que es el comportamiento historico (legacy #40).
    ("api_keys", "scopes", "TEXT NOT NULL DEFAULT '*'"),
    # Duenio de la clave. Sin ella, el borrado GDPR de claves de un usuario
    # (`revoke_all_api_keys_for_user`) no encuentra ninguna y devuelve 0, y
    # `get_user_id_from_key_id` devuelve None (migracion legacy #40).
    ("api_keys", "user_id", "INTEGER"),
]


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    for table, column, definition in _COLUMNS:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}")


def downgrade() -> None:
    if not _is_postgres():
        return
    for table, column, _definition in _COLUMNS:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}")
