"""v129: ``user_id`` junto a ``user_key`` en todas las tablas de usuario (ADR-030 fase 2).

Revision ID: v129_user_id_fase2
Revises: v128_rls_tenant_policies
Create Date: 2026-09-14

Qué corrige
-----------
La identidad de las tablas de usuario es ``user_key = sha256(email)[:16]``
(``shared.identity.user_key_from_email``): cambiar de correo estrena clave y
con ella se pierden favoritos, reglas, vistas, descartes, notificaciones y
preferencias. ADR-030 §A fija tres fases; ésta es la **segunda**: columna
``user_id`` donde falte, backfill por email y lectura dual en los
repositorios. ``user_key`` se sigue escribiendo y no se retira nada — eso es
la fase 3 —, pero desde esta revisión el dato queda anclado al ``users.id`` y
el correo puede cambiar sin perderlo.

Inventario (docs/database-schema.md, medido el 2026-09-14)
----------------------------------------------------------
Doce tablas llevan ``user_key``. Tres ya tenían ``user_id`` anulable:

* ``watchlist_cpv``   (v53: columna, FK a ``users`` e índice ``idx_wl_user_id``)
* ``watchlist_items`` (v55: columna suelta, sin FK ni índice)
* ``watchlist_rules`` (v55: columna suelta, sin FK ni índice)

Nueve no la tenían y la reciben aquí: ``audit_log``, ``notification_reads``,
``pending_digests``, ``radar_dismissals``, ``saved_filters``,
``user_notifications``, ``user_profiles``, ``watchlist_empresas`` y
``user_event_prefs``.

Lo que hace esta revisión
-------------------------
1. ``ADD COLUMN IF NOT EXISTS user_id INTEGER`` en las nueve.
2. FK ``fk_<tabla>_user_id`` → ``users(id) ON DELETE SET NULL`` en las once
   que no la tenían (``watchlist_cpv`` ya la trae de v53). ``SET NULL`` y no
   ``CASCADE``: el dato personal se anonimiza por GDPR (``services/gdpr.py``),
   no se pierde porque desaparezca la fila de ``users``. Se instala
   ``NOT VALID`` como en v64 —protege las escrituras nuevas sin escanear ni
   bloquear— y se valida al final, una vez el backfill sólo ha escrito ids que
   existen en ``users``.
3. Backfill **en SQL**: Postgres reproduce la derivación de Python con
   ``substr(encode(sha256(convert_to(lower(btrim(seed)), 'UTF8')), 'hex'), 1, 16)``
   sobre ``seed = COALESCE(NULLIF(email, ''), 'user:' || id)`` —la misma
   semilla que ``user_key_from_email``—. ``tests/test_user_id_cambio_email_
   integration.py`` comprueba la equivalencia clave a clave contra la función
   de Python. La única divergencia teórica es un correo con espacios Unicode
   exóticos o letras fuera de ASCII con caja distinta según la collation; no
   hay ninguno en ``users`` y, si lo hubiera, esa fila queda sin resolver y la
   lectura dual la sigue sirviendo por ``user_key``.
   Las claves se materializan una vez en una tabla temporal (patrón de v64) y
   cada tabla recibe UN ``UPDATE ... WHERE user_id IS NULL``. No se trocea:
   Alembic ejecuta la revisión en una transacción, así que un lote no
   liberaría locks antes del ``COMMIT``; y el predicado ``user_id IS NULL`` lo
   hace reanudable por construcción si hubiera que repetirlo a mano.
   ``audit_log`` resuelve además las filas cuyo ``user_key`` es el ``users.id``
   en texto —lo que escriben los llamadores de ``log_event`` que ya pasan el id
   del principal (ver ``scripts/check_user_key_ratchet.py``)—.
4. Índice ``idx_<tabla>_user_id`` en las once que no lo tienen, creado
   ``CONCURRENTLY`` en ``autocommit_block`` (v64): son tablas vivas.

Lo que NO hace
--------------
* No toca las PK ni los UNIQUE tecleados por ``user_key`` (``user_profiles``
  y ``radar_dismissals`` lo llevan en la PK): recrearlos es la migración cara
  de la fase 3 y exige su propio ``--sql`` antes del ``apply``. Mientras
  tanto los repositorios evitan duplicar filas comprobando la identidad dual
  antes de insertar.
* No resuelve el 100 %: API keys sin usuario y filas huérfanas quedan con
  ``user_id IS NULL`` y las sirve la rama ``user_key`` de la lectura dual.

Downgrade: retira sólo lo que esta revisión añadió (índices, FKs y las nueve
columnas nuevas); las tres columnas previas se conservan.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v129_user_id_fase2"
down_revision: str | Sequence[str] | None = "v128_rls_tenant_policies"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Tablas que reciben la columna en esta revisión.
TABLAS_NUEVAS: tuple[str, ...] = (
    "audit_log",
    "notification_reads",
    "pending_digests",
    "radar_dismissals",
    "saved_filters",
    "user_notifications",
    "user_profiles",
    "watchlist_empresas",
    "user_event_prefs",
)

#: Tablas que ya tenían ``user_id`` y sólo reciben FK, índice y backfill.
TABLAS_PREVIAS: tuple[str, ...] = (
    "watchlist_cpv",
    "watchlist_items",
    "watchlist_rules",
)

#: Todas las tablas con ``user_key``: las que backfillea esta revisión.
TABLAS: tuple[str, ...] = TABLAS_NUEVAS + TABLAS_PREVIAS

#: ``watchlist_cpv`` trae FK e índice desde v53: no se duplican.
_SIN_FK: frozenset[str] = frozenset({"watchlist_cpv"})
_SIN_INDICE: frozenset[str] = frozenset({"watchlist_cpv"})

#: Derivación de ``user_key`` en SQL, sobre la fila ``u`` de ``users``. Es la
#: transcripción de ``shared.identity.user_key_from_email``::
#:
#:     sha256((email or f"user:{id}").strip().lower())[:16]
CLAVE_SQL = (
    "substr(encode(sha256(convert_to(lower(btrim("
    "COALESCE(NULLIF(u.email, ''), 'user:' || u.id::text), E' \\t\\r\\n')), 'UTF8')), "
    "'hex'), 1, 16)"
)

_CREAR_CLAVES = (
    "CREATE TEMPORARY TABLE v129_claves ("
    "user_key TEXT PRIMARY KEY, user_id INTEGER NOT NULL) ON COMMIT DROP"
)

_SEMBRAR_CLAVES = (
    "INSERT INTO v129_claves (user_key, user_id) "
    f"SELECT {CLAVE_SQL}, u.id FROM users u "
    "ON CONFLICT (user_key) DO NOTHING"
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def sql_backfill(tabla: str) -> str:
    """``UPDATE`` que resuelve ``user_id`` por ``user_key`` en ``tabla``.

    Público para que el test de integración lo ejecute sobre datos sembrados
    y compruebe que resuelve exactamente lo que resolvería Python.
    """
    return (
        f"UPDATE {tabla} AS x SET user_id = k.user_id "
        "FROM v129_claves AS k "
        "WHERE x.user_id IS NULL AND x.user_key = k.user_key"
    )


#: ``audit_log`` lleva además filas con ``user_key = str(users.id)``. El patrón
#: acota a enteros cortos: una clave sha de 16 hex sólo es «todo dígitos» con
#: probabilidad ínfima y, aun así, nunca tendría nueve cifras o menos.
SQL_BACKFILL_AUDIT_POR_ID = (
    "UPDATE audit_log AS x SET user_id = u.id "
    "FROM users AS u "
    "WHERE x.user_id IS NULL AND x.user_key ~ '^[0-9]{1,9}$' "
    "AND x.user_key::int = u.id"
)


def _add_user_id(tabla: str) -> None:
    op.execute(f"ALTER TABLE {tabla} ADD COLUMN IF NOT EXISTS user_id INTEGER")


def _add_fk(tabla: str) -> None:
    fk = f"fk_{tabla}_user_id"
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_constraint "
        f"WHERE conname = '{fk}' AND conrelid = '{tabla}'::regclass) THEN "
        f"ALTER TABLE {tabla} ADD CONSTRAINT {fk} "
        "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL NOT VALID; "
        "END IF; END $$"
    )


def _validate_fk(tabla: str) -> None:
    # Idempotente: validar una FK ya válida es un no-op para Postgres.
    op.execute(f"ALTER TABLE {tabla} VALIDATE CONSTRAINT fk_{tabla}_user_id")


def upgrade() -> None:
    if not _is_postgres():
        return

    existentes = set(sa.inspect(op.get_bind()).get_table_names())
    presentes = [t for t in TABLAS if t in existentes]

    for tabla in presentes:
        if tabla in TABLAS_NUEVAS:
            _add_user_id(tabla)
        if tabla not in _SIN_FK:
            _add_fk(tabla)

    op.execute(_CREAR_CLAVES)
    op.execute(_SEMBRAR_CLAVES)
    for tabla in presentes:
        op.execute(sql_backfill(tabla))
    if "audit_log" in presentes:
        op.execute(SQL_BACKFILL_AUDIT_POR_ID)

    # Sólo tras el backfill: cada id escrito arriba sale de ``users``, y las
    # tres columnas previas nunca apuntaron a filas borradas (``users`` no se
    # borra, se anonimiza).
    for tabla in presentes:
        if tabla not in _SIN_FK:
            _validate_fk(tabla)

    # Los índices recorren tablas vivas: concurrentes y al final (v64).
    with op.get_context().autocommit_block():
        for tabla in presentes:
            if tabla in _SIN_INDICE:
                continue
            op.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_{tabla}_user_id ON {tabla} (user_id)"
            )


def downgrade() -> None:
    if not _is_postgres():
        return

    existentes = set(sa.inspect(op.get_bind()).get_table_names())
    presentes = [t for t in TABLAS if t in existentes]

    with op.get_context().autocommit_block():
        for tabla in reversed(presentes):
            if tabla in _SIN_INDICE:
                continue
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS idx_{tabla}_user_id")

    for tabla in reversed(presentes):
        if tabla not in _SIN_FK:
            op.execute(f"ALTER TABLE {tabla} DROP CONSTRAINT IF EXISTS fk_{tabla}_user_id")
        if tabla in TABLAS_NUEVAS:
            op.execute(f"ALTER TABLE {tabla} DROP COLUMN IF EXISTS user_id")
