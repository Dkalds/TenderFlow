"""v183: una clave de API activa necesita dueño y caducidad (``CHECK … NOT VALID``).

Revision ID: v183_api_keys_activa_con_dueno
Revises: v182_unique_user_key_parciales
Create Date: 2026-11-14

Qué corrige
-----------
Medido en producción el 2026-10-09: 89 claves activas, todas sin ``user_id`` ni
``expires_at``. Una clave sin dueño no se revoca al dar de baja a nadie y una
sin caducidad no caduca nunca. Desde 2026-10-25 ``ApiKeyRepository.insert``
exige los dos, pero la tabla no: cualquier otro ``INSERT`` (un script, una
consola SQL) puede volver a crearlas.

Lo que hace
-----------
``CHECK (is_active = 0 OR (user_id IS NOT NULL AND expires_at IS NOT NULL))``
con ``NOT VALID``: rige para toda fila nueva o modificada desde ya, sin leer ni
bloquear las existentes. Las 89 heredadas siguen como están hasta que el
propietario las revise y revoque (tarjeta «Claves de API» de la administración en Ops); revocar es
``is_active = 0``, que la restricción admite.

Lo que NO hace
--------------
* No ``VALIDATE CONSTRAINT``: fallaría mientras quede una heredada activa. Va
  en una revisión posterior, tras la revocación.
* No revoca nada ni pone caducidades: qué clave sigue en uso es decisión del
  propietario.

``NOT VALID`` también rige para los ``UPDATE``: el de ``last_used`` al
autenticar falla —y ``update_last_used`` se lo traga— en toda fila activa que
no cumpla la condición. En producción, las claves sin dueño ya no llegan a él
(la validación las rechaza desde 2026-07-27), pero **una clave con dueño y sin
caducidad sí**: se seguiría usando con su ``last_used`` congelado, y la tarjeta
de administración la enseñaría como parada. Antes del ``apply`` en producción:

    SELECT count(*) FROM api_keys
     WHERE is_active = 1 AND user_id IS NOT NULL AND expires_at IS NULL;

Si sale más de 0, ponerles caducidad (o revocarlas) antes de aplicar.

Downgrade: quita la restricción.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v183_api_keys_activa_con_dueno"
down_revision: str | Sequence[str] | None = "v182_unique_user_key_parciales"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RESTRICCION = "ck_api_keys_activa_con_dueno"
CONDICION = "is_active = 0 OR (user_id IS NOT NULL AND expires_at IS NOT NULL)"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    # `DO` para que reaplicar sobre una base que ya la tiene no falle.
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_constraint "
        f"  WHERE conname = '{RESTRICCION}' AND conrelid = 'api_keys'::regclass) THEN "
        f"ALTER TABLE api_keys ADD CONSTRAINT {RESTRICCION} CHECK ({CONDICION}) NOT VALID; "
        "END IF; END $$"
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute(f"ALTER TABLE api_keys DROP CONSTRAINT IF EXISTS {RESTRICCION}")
