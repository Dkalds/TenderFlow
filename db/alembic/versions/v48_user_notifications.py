"""Migracion v48 -- tabla user_notifications (alertas in-app por usuario).

Reemplaza el mecanismo de notify() global por persistencia per-usuario.
El job de alertas de reglas escribe aqui; el endpoint /notifications la lee.

UNIQUE(user_key, licitacion_id, type) garantiza idempotencia:
INSERT OR IGNORE evita duplicados en re-ejecuciones del job.

'type' puede ser:
  - 'rule_match'    : match de una regla de watchlist
  - 'deadline_30'   : vencimiento en 30 dias
  - 'deadline_7'    : vencimiento en 7 dias
  - 'deadline_1'    : vencimiento en 1 dia
  - 'renovacion_30' : fin de contrato en 30 dias
  - 'renovacion_7'  : fin de contrato en 7 dias

Revision ID: v48_user_notifications
Revises: v47_watchlist_rules_email
Create Date: 2026-07-05
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v48_user_notifications"
down_revision: str | Sequence[str] | None = "v47_watchlist_rules_email"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_notifications (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_key     TEXT NOT NULL,
            created_at   TEXT NOT NULL DEFAULT (datetime('now','utc')),
            type         TEXT NOT NULL,
            title        TEXT,
            body         TEXT,
            licitacion_id TEXT,
            rule_id      INTEGER,
            read_at      TEXT,
            UNIQUE(user_key, licitacion_id, type)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_notif_user_read "
        "ON user_notifications(user_key, read_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_user_notif_user_read")
    op.execute("DROP TABLE IF EXISTS user_notifications")
