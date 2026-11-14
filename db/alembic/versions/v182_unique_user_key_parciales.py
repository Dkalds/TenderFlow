"""v182: los ``UNIQUE`` por ``user_key`` de ``watchlist_*`` y ``follows`` pasan a parciales.

Revision ID: v182_unique_user_key_parciales
Revises: v181_user_id_watchlist_follows
Create Date: 2026-11-14

ADR-030 fase 3: la revisión que ``v181`` dejó para después de su despliegue.

Qué corrige
-----------
Tras v181 las tres tablas son únicas por ``user_id`` (índice parcial
``uq_<tabla>_user_id``) y **además** por la clave derivada del correo:

* ``watchlist_items``    → ``UNIQUE (user_key, id_externo)``
* ``watchlist_empresas`` → ``UNIQUE (user_key, empresa_id)``
* ``follows``            → ``uq_follows_user_target (user_key, target_type, target_id, kind)``

Quien registra un correo que otra cuenta dejó hereda su ``user_key``: si sigue
lo mismo que ella, su ``INSERT`` choca con la fila ajena (500 en favoritos, 503
en ``follows``). La clave solo identifica a las filas que el backfill no pudo
resolver a un ``user_id``.

Lo que hace
-----------
Por tabla, en este orden para que nunca haya un instante sin unicidad:

1. ``CREATE UNIQUE INDEX uq_<tabla>_user_key (user_key, …) WHERE user_id IS
   NULL``: las filas sin id siguen tecleadas por la clave, como hasta ahora.
2. Quita el ``UNIQUE`` entero por ``user_key``. Se busca por sus columnas en
   ``pg_constraint`` y no por nombre: ``watchlist_items`` y
   ``watchlist_empresas`` nacieron con una restricción sin nombre (v55), y una
   base que ya las tuviera antes de v55 pudo llamarlas de otra forma.

Ningún ``ON CONFLICT`` del código arbitra ya por esas restricciones (desde v181
lo hacen por ``user_id``), así que quitarlas no rompe ninguna escritura.

Orden de despliegue
-------------------
**Después de v181 y de su código**, que es lo que dejó de arbitrar por la
clave. El código de antes de v181 sí lo hacía: no se aplica sobre él.

Downgrade: vuelve a crear los ``UNIQUE`` enteros. Falla si, entretanto, dos
cuentas guardaron el mismo objetivo bajo la misma clave —que es justo lo que
esta revisión permite—; esas filas se revisan a mano antes de bajar.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v182_unique_user_key_parciales"
down_revision: str | Sequence[str] | None = "v181_user_id_watchlist_follows"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: ``tabla → columnas`` que acompañan a ``user_key`` en su clave de unicidad
#: (las mismas que ``TABLAS_UNICAS`` de v181; una migración no importa de otra).
TABLAS: dict[str, tuple[str, ...]] = {
    "watchlist_items": ("id_externo",),
    "watchlist_empresas": ("empresa_id",),
    "follows": ("target_type", "target_id", "kind"),
}

#: Nombre que recupera el ``UNIQUE`` entero al bajar. ``follows`` conserva el
#: suyo de v130; las otras dos, el que Postgres pone a una restricción sin nombre.
NOMBRE_ENTERO: dict[str, str] = {
    "watchlist_items": "watchlist_items_user_key_id_externo_key",
    "watchlist_empresas": "watchlist_empresas_user_key_empresa_id_key",
    "follows": "uq_follows_user_target",
}


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def indice(tabla: str) -> str:
    """Nombre del índice único parcial por ``user_key`` de ``tabla``."""
    return f"uq_{tabla}_user_key"


def columnas(tabla: str) -> str:
    return ", ".join(("user_key", *TABLAS[tabla]))


def sql_indice_parcial(tabla: str) -> str:
    return (
        f"CREATE UNIQUE INDEX IF NOT EXISTS {indice(tabla)} "
        f"ON {tabla} ({columnas(tabla)}) WHERE user_id IS NULL"
    )


def sql_quitar_unique_entero(tabla: str) -> str:
    """``DO`` que quita el ``UNIQUE`` cuyas columnas son exactamente las de ``tabla``.

    Compara conjuntos de nombres de columna: el orden en la restricción no
    importa, y una restricción con otras columnas no se toca.
    """
    lista = ", ".join(f"'{c}'" for c in ("user_key", *TABLAS[tabla]))
    return (
        "DO $$ DECLARE r record; BEGIN "
        "FOR r IN SELECT con.conname FROM pg_constraint con "
        f"WHERE con.conrelid = '{tabla}'::regclass AND con.contype = 'u' "
        "AND (SELECT array_agg(a.attname::text ORDER BY a.attname) FROM pg_attribute a "
        "     WHERE a.attrelid = con.conrelid AND a.attnum = ANY(con.conkey)) "
        f"  = (SELECT array_agg(x ORDER BY x) FROM unnest(ARRAY[{lista}]) AS x) "
        f"LOOP EXECUTE format('ALTER TABLE {tabla} DROP CONSTRAINT %I', r.conname); "
        "END LOOP; END $$"
    )


def _presentes() -> list[str]:
    existentes = set(sa.inspect(op.get_bind()).get_table_names())
    return [t for t in TABLAS if t in existentes]


def upgrade() -> None:
    if not _is_postgres():
        return
    for tabla in _presentes():
        op.execute(sql_indice_parcial(tabla))
        op.execute(sql_quitar_unique_entero(tabla))


def downgrade() -> None:
    if not _is_postgres():
        return
    for tabla in _presentes():
        op.execute(
            f"ALTER TABLE {tabla} ADD CONSTRAINT {NOMBRE_ENTERO[tabla]} UNIQUE ({columnas(tabla)})"
        )
        op.execute(f"DROP INDEX IF EXISTS {indice(tabla)}")
