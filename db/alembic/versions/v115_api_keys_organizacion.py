"""v115: ``api_keys.organization_id`` — claves de equipo, no solo personales (C2.3, D25).

Qué corrige
-----------
Dos cosas que el hecho 9 del plan complementario mide:

1. **Las claves no se pueden crear desde el producto.** `api/auth.py::create_api_key`
   existe y **solo la usa un script**; `/me/keys` lista y rota, no crea. Para
   tener una clave hay que pedírsela al mantenedor.
2. **`api_key_tiers` existe desde `v28` con su columna `tier` en `api_keys`, y
   ninguna ruta ni middleware la lee** — cero coincidencias de `tier` en
   `api/auth.py`, `api/middleware.py`, `api/scopes.py` y
   `services/rate_limiting.py`. Los tres tiers están sembrados y no significan
   nada: una clave `free` y una `enterprise` reciben el mismo rate limit.

Esta revisión añade lo que falta para la primera y no toca la segunda: el tier
ya está en la tabla, lo que faltaba era **leerlo**, y eso es código.

``organization_id``
-------------------
Nullable. Una clave sin organización es **personal**, que es lo que son todas
las de hoy: retroactivamente correcto sin backfill.

`ON DELETE CASCADE` y no `SET NULL`: al borrar una organización, sus claves
mueren con ella. Convertirlas en personales del creador sería regalarle a una
persona el acceso que tenía como miembro de un equipo que ya no existe — y sin
que nadie lo decida.

``created_by``
--------------
Quién la creó. En una clave de organización el `user_id` solo, sin esto, no
distingue «la clave de Ana» de «la clave del equipo que creó Ana», y esa
diferencia importa cuando Ana se va.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v115_api_keys_organizacion"
down_revision: str | Sequence[str] | None = "v114_lic_organo_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return

    inspector = sa.inspect(op.get_bind())
    if "api_keys" not in inspector.get_table_names():
        return
    columnas = {c["name"] for c in inspector.get_columns("api_keys")}

    if "organization_id" not in columnas:
        op.add_column("api_keys", sa.Column("organization_id", sa.Integer, nullable=True))
        op.create_foreign_key(
            "fk_api_keys_organization",
            "api_keys",
            "organizations",
            ["organization_id"],
            ["id"],
            ondelete="CASCADE",
        )
        # Parcial: las claves personales son mayoría y no se consultan por
        # organización nunca.
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_api_keys_organization "
            "ON api_keys (organization_id) WHERE organization_id IS NOT NULL"
        )

    if "created_by" not in columnas:
        op.add_column("api_keys", sa.Column("created_by", sa.Integer, nullable=True))


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("DROP INDEX IF EXISTS idx_api_keys_organization")
    op.execute("ALTER TABLE api_keys DROP CONSTRAINT IF EXISTS fk_api_keys_organization")
    for columna in ("created_by", "organization_id"):
        op.execute(f"ALTER TABLE api_keys DROP COLUMN IF EXISTS {columna}")
