"""v105: ``users.oauth_provider`` acotado a los proveedores que existen.

Revision ID: v105_users_oauth_provider
Revises: v104_org_invitaciones
Create Date: 2026-09-06

La columna existe desde el génesis (``baseline002_pg_core_genesis``) junto con
``UNIQUE (oauth_provider, oauth_sub)``, pero era texto libre porque solo había
un proveedor y nadie podía equivocarse. Con dos (Google y Microsoft Entra ID,
D17) el texto libre sí muerde: un ``"Google"`` con mayúscula o un ``"msft"``
escrito en el sitio equivocado no colisiona con la fila existente, así que la
misma persona acabaría con **dos** identidades y dos espacios personales, y el
síntoma aparecería semanas después como «he perdido mis favoritos».

``NOT VALID`` a propósito: la restricción gobierna lo que se escriba de aquí en
adelante y no bloquea el despliegue por una fila histórica que esta revisión no
puede inspeccionar (producción va por detrás del repo — hecho 1 del plan). Para
validarla más adelante, cuando se haya comprobado el contenido real:

    ALTER TABLE users VALIDATE CONSTRAINT ck_users_oauth_provider;

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v105_users_oauth_provider"
down_revision: str | Sequence[str] | None = "v104_org_invitaciones"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Fuente única del enumerado en SQL. El equivalente en Python es
#: ``api.routes.auth.OAUTH_PROVIDERS``; si se añade un proveedor hay que tocar
#: los dos, y ``tests/test_s1_oauth_providers.py`` comprueba que no divergen.
_PROVIDERS = ("google", "microsoft")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    valores = ", ".join(f"'{p}'" for p in _PROVIDERS)
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT ck_users_oauth_provider "
        f"CHECK (oauth_provider IS NULL OR oauth_provider IN ({valores})) NOT VALID"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_oauth_provider")
