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
from alembic import op

revision: str = "v26_audit_hash_chain"
down_revision: str | Sequence[str] | None = "v25_api_keys_prefix"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    try:
        op.add_column("audit_log", sa.Column("prev_hash", sa.Text(), nullable=True))
    except Exception:
        pass
    try:
        op.add_column("audit_log", sa.Column("this_hash", sa.Text(), nullable=True))
    except Exception:
        pass


def downgrade() -> None:
    pass
