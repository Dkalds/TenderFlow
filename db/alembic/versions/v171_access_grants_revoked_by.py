"""v171: ``access_grants.revoked_by`` guarda quién revocó una concesión.

Revision ID: v171_access_grants_revoked_by
Revises: v170_actas_puntuaciones
Create Date: 2026-11-04

Qué falla hoy
-------------
``access_grants`` guarda quién concedió (``granted_by``) pero no quién revocó:
el único rastro era la fila ``access_grant.revoked`` de ``audit_log``, que se
escribía después de confirmar la revocación y podía perderse. ADR-039 hace de
esa fila una condición de la operación; esta columna deja además el dato en la
propia concesión, como ya estaba ``granted_by``.

Qué hace
--------
Añade ``revoked_by integer`` nullable con FK a ``users(id)`` ``ON DELETE SET
NULL``, la misma forma que ``granted_by`` (``v95``). Las filas existentes
quedan con ``NULL``: no se sabe quién las revocó.

La FK se crea ``NOT VALID`` y se valida en un segundo paso. Con la columna
recién creada y toda a ``NULL`` la validación no tiene nada que comprobar, y
``access_grants`` tiene decenas de filas; se separa igual para no tomar el lock
de validación junto al ``ADD COLUMN``.

Sin índice: nadie filtra por quién revocó, y la FK solo se recorre al borrar un
usuario, que es raro y cuya cascada ya recorre ``granted_by`` sin índice.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v171_access_grants_revoked_by"
down_revision: str | Sequence[str] | None = "v170_actas_puntuaciones"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.execute("ALTER TABLE access_grants ADD COLUMN IF NOT EXISTS revoked_by INTEGER")
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_constraint "
        "WHERE conname = 'fk_access_grants_revoked_by') THEN "
        "ALTER TABLE access_grants ADD CONSTRAINT fk_access_grants_revoked_by "
        "FOREIGN KEY (revoked_by) REFERENCES users(id) ON DELETE SET NULL NOT VALID; "
        "END IF; END $$"
    )
    op.execute("ALTER TABLE access_grants VALIDATE CONSTRAINT fk_access_grants_revoked_by")


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("ALTER TABLE access_grants DROP CONSTRAINT IF EXISTS fk_access_grants_revoked_by")
    op.execute("ALTER TABLE access_grants DROP COLUMN IF EXISTS revoked_by")
