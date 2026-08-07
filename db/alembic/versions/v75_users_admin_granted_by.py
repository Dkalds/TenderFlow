"""v75: columna ``users.admin_granted_by`` (procedencia de la concesión de admin).

Revision ID: v75_users_admin_granted_by
Revises: v74_dlq_unique_unresolved
Create Date: 2026-08-07

``users.is_admin`` es un booleano sin procedencia, y ``_sync_oauth_admin`` refleja
``OAUTH_ADMIN_EMAILS`` sobre él en ambos sentidos: quien se promovió desde el
panel (``admin_set_admin``) y además entra por Google pierde el flag en su
siguiente login. Sin saber QUIÉN concedió el flag no se puede decidir quién puede
retirarlo. Esta columna registra el origen (``oauth`` / ``panel``); el valor NULL
queda para las concesiones preexistentes, de origen desconocido.

Columna nullable → ``ADD COLUMN`` es metadata-only en Postgres (sin reescritura de
tabla, sin lock largo), por eso no necesita ``CONCURRENTLY``.

SIGUE PENDIENTE (código, no incluido en esta migración): cablear la columna —
``admin_set_admin`` debe escribir ``'panel'``, ``_sync_oauth_admin`` debe escribir
``'oauth'`` al promover y degradar SOLO las concesiones de origen ``oauth``. La
columna es inerte hasta ese cambio. Ítem de backlog "[P2] El origen de una
concesión de is_admin no se registra".

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v75_users_admin_granted_by"
down_revision: str | Sequence[str] | None = "v74_dlq_unique_unresolved"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.add_column("users", sa.Column("admin_granted_by", sa.Text(), nullable=True))


def downgrade() -> None:
    if not _is_postgres():
        return
    op.drop_column("users", "admin_granted_by")
