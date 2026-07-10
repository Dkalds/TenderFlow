"""Migración v26 — Cadena de hash en audit_log para integridad verificable.

Añade las columnas ``prev_hash`` y ``this_hash`` a la tabla ``audit_log``,
formando una cadena de bloques inmutable que detecta manipulaciones
retroactivas de los registros de auditoría.

- ``prev_hash``: SHA-256 del registro anterior (NULL para el primero).
- ``this_hash``: SHA-256(prev_hash + action + detail + created_at + user_key).

Revision ID: v26_audit_hash_chain
Revises: v25_api_keys_prefix
Create Date: 2026-06-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "v26_audit_hash_chain"
down_revision: str | Sequence[str] | None = "v25_api_keys_prefix"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # audit_log no existe todavía en un bootstrap Postgres fresco (la crea
    # v51_pg_legacy_tables_backfill, mucho más adelante en la cadena) --
    # y en general, no usar try/except: en Postgres un ADD COLUMN fallido
    # (columna o tabla inexistente) deja la transacción abortada para el
    # resto de la migración, a diferencia de SQLite. En modo offline (--sql)
    # no hay conexión real que introspeccionar.
    if context.is_offline_mode():
        op.add_column("audit_log", sa.Column("prev_hash", sa.Text(), nullable=True))
        op.add_column("audit_log", sa.Column("this_hash", sa.Text(), nullable=True))
        return
    insp = sa.inspect(op.get_bind())
    if "audit_log" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("audit_log")}
    if "prev_hash" not in cols:
        op.add_column("audit_log", sa.Column("prev_hash", sa.Text(), nullable=True))
    if "this_hash" not in cols:
        op.add_column("audit_log", sa.Column("this_hash", sa.Text(), nullable=True))


def downgrade() -> None:
    pass
