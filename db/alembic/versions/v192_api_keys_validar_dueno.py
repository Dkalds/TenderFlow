"""v192: valida ``ck_api_keys_activa_con_dueno`` (``VALIDATE CONSTRAINT`` de ``v183``).

Revision ID: v192_api_keys_validar_dueno
Revises: v191_adj_identidad_normalizada
Create Date: 2026-11-25

Qué falta
---------
``v183`` añadió ``CHECK (is_active = 0 OR (user_id IS NOT NULL AND expires_at IS
NOT NULL)) NOT VALID``: rige para las filas nuevas o modificadas, pero Postgres
no garantiza que las existentes la cumplan, así que el planificador no puede
apoyarse en ella y nada impide que quede alguna clave heredada activa. El
``VALIDATE`` quedó para después de que el propietario revocara las heredadas.

Lo que hace
-----------
Comprueba antes que ninguna clave activa incumple la condición y, si alguna lo
hace, para con un error que dice cuántas y qué hacer —revocarlas en la tarjeta
«Claves de API» de Ops > Administración—, en vez del mensaje genérico de
Postgres. Si no, ``VALIDATE CONSTRAINT``: toma ``SHARE UPDATE EXCLUSIVE``, que
no bloquea lecturas ni escrituras, y recorre la tabla una vez. Validar una
restricción ya validada no hace nada, así que reaplicar es seguro.

Se aplica con ``migrate.yml`` **desde la rama, antes de mergear**: si falla,
``master`` no se queda por delante de la base.

Downgrade: no hace nada. Una restricción validada no se puede volver a
``NOT VALID`` sin quitarla, y la de ``v183`` sigue siendo la misma.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v192_api_keys_validar_dueno"
down_revision: str | Sequence[str] | None = "v191_adj_identidad_normalizada"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RESTRICCION = "ck_api_keys_activa_con_dueno"
INCUMPLE = "is_active <> 0 AND (user_id IS NULL OR expires_at IS NULL)"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.execute(
        "DO $$ DECLARE n bigint; BEGIN "
        f"SELECT count(*) INTO n FROM api_keys WHERE {INCUMPLE}; "
        "IF n > 0 THEN RAISE EXCEPTION "
        "'% claves de API activas sin dueño o sin caducidad: revocalas en Ops > "
        "Administración > Claves de API antes de validar', n; "
        "END IF; END $$"
    )
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(f"ALTER TABLE api_keys VALIDATE CONSTRAINT {RESTRICCION}")


def downgrade() -> None:
    return
