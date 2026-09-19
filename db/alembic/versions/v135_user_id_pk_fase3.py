"""v135: ``user_profiles`` y ``radar_dismissals`` pasan a tener la PK en ``user_id`` (ADR-030 fase 3).

Revision ID: v135_user_id_pk_fase3
Revises: v136_tecnologia_verdad_unica
Create Date: 2026-09-18

Qué corrige
-----------
v129 (fase 2) puso ``user_id`` en las doce tablas de usuario, pero dejó a
propósito las dos cuya **clave primaria** es ``user_key``:

* ``user_profiles``    — ``PRIMARY KEY (user_key)`` (v49)
* ``radar_dismissals`` — ``PRIMARY KEY (user_key, id_externo)`` (v76)

Mientras la PK sea la clave derivada del correo, un usuario que cambia de
dirección puede acabar con dos perfiles o con el mismo expediente descartado
dos veces, y los repositorios lo esquivan con un ``UPDATE`` por identidad dual
antes de cada ``INSERT``. Esta revisión es «la migración cara» que v129 aplazó:
la identidad de la fila pasa a ser ``users.id`` y la base, no el repositorio,
impide el duplicado.

Lo que hace, por tabla
----------------------
1. **Backfill** de las filas con ``user_id IS NULL`` —la misma derivación SQL
   de v129, repetida aquí porque una migración no importa de otra—. Recoge lo
   escrito sin id entre v129 y el despliegue del código de esta fase.
2. **Falla con ruido** (``RAISE EXCEPTION``, la transacción entera se deshace)
   si queda alguna fila sin ``user_id`` o si dos filas comparten la identidad
   nueva. No se borra ni se fusiona nada en silencio: una fila sin dueño
   resoluble o un duplicado son dato de alguien, y decidir qué se conserva es
   una decisión humana. El mensaje incluye la consulta que las lista.
3. PK recreada: ``(user_id)`` y ``(user_id, id_externo)``; ``user_id`` pasa a
   ``NOT NULL`` y ``user_key`` deja de serlo — en ``user_profiles`` ya no se
   escribe (el repositorio sólo pone ``user_id``); en ``radar_dismissals`` se
   sigue escribiendo porque ``user_notifications`` y ``follows``, a los que
   alimenta, siguen tecleadas por ``user_key``.
4. La unicidad vieja se conserva como índice ``UNIQUE`` de transición
   (``uq_<tabla>_user_key``). No es nostalgia: el código de la fase 2 hace
   ``ON CONFLICT (user_key)`` / ``(user_key, id_externo)`` y, sin un índice que
   case, Postgres rechaza el ``INSERT`` entero. Con él, el código viejo sigue
   funcionando sobre el schema nuevo durante el despliegue. Los ``NULL`` no
   chocan entre sí, así que no estorba a los perfiles nuevos, que ya no llevan
   clave. Se retira con la columna.
5. La FK ``fk_<tabla>_user_id`` pasa de ``ON DELETE SET NULL`` a ``CASCADE``:
   ``SET NULL`` sobre una columna de PK es un error esperando a ocurrir, y
   ADR-030 §D ya clasifica perfil y descartes como dato **personal**, que se va
   con la persona. ``users`` no se borra en producción (se anonimiza), así que
   el cambio sólo decide qué pasaría si alguien lo hiciera.

Orden de despliegue
-------------------
**Esta revisión se aplica antes de desplegar el código de la fase 3.** Los
upserts nuevos usan ``ON CONFLICT (user_id)`` / ``(user_id, id_externo)``, que
no existen hasta aquí. El orden inverso (código viejo sobre schema nuevo) sí
funciona gracias al índice de transición del punto 4, y porque el código viejo
siempre escribe ``user_id``: ``require_any_auth`` lo adjunta a todo principal,
así que el ``NOT NULL`` no rechaza ninguna escritura real.

Antes del ``apply`` en producción: ``alembic upgrade v135_user_id_pk_fase3
--sql`` para revisar el DDL, y las dos consultas de ``sql_huerfanas`` /
``sql_duplicados`` a mano para saber si el ``RAISE`` va a saltar.

Downgrade: vuelve a la PK por ``user_key``. Las filas escritas sin clave (los
perfiles de esta fase) la recuperan derivándola de ``users``; si alguna no
puede, o si dos colisionan, falla igual que el upgrade.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v135_user_id_pk_fase3"
down_revision: str | Sequence[str] | None = "v136_tecnologia_verdad_unica"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Tabla → columnas de la PK nueva (``user_id`` primero) y de la vieja.
PK_NUEVA: dict[str, tuple[str, ...]] = {
    "user_profiles": ("user_id",),
    "radar_dismissals": ("user_id", "id_externo"),
}
PK_VIEJA: dict[str, tuple[str, ...]] = {
    "user_profiles": ("user_key",),
    "radar_dismissals": ("user_key", "id_externo"),
}

TABLAS: tuple[str, ...] = tuple(PK_NUEVA)

#: Derivación de ``user_key`` en SQL sobre la fila ``u`` de ``users``: la
#: misma transcripción de ``shared.identity.user_key_from_email`` que v129.
CLAVE_SQL = (
    "substr(encode(sha256(convert_to(lower(btrim("
    "COALESCE(NULLIF(u.email, ''), 'user:' || u.id::text), E' \\t\\r\\n')), 'UTF8')), "
    "'hex'), 1, 16)"
)

_CREAR_CLAVES = (
    "CREATE TEMPORARY TABLE v135_claves ("
    "user_key TEXT PRIMARY KEY, user_id INTEGER NOT NULL) ON COMMIT DROP"
)

_SEMBRAR_CLAVES = (
    "INSERT INTO v135_claves (user_key, user_id) "
    f"SELECT {CLAVE_SQL}, u.id FROM users u "
    "ON CONFLICT (user_key) DO NOTHING"
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def sql_backfill(tabla: str) -> str:
    """``UPDATE`` que resuelve ``user_id`` por ``user_key`` (igual que v129)."""
    return (
        f"UPDATE {tabla} AS x SET user_id = k.user_id "
        "FROM v135_claves AS k "
        "WHERE x.user_id IS NULL AND x.user_key = k.user_key"
    )


def sql_huerfanas(tabla: str) -> str:
    """Filas que no se pueden mover a la PK nueva: sin ``user_id``."""
    return f"SELECT user_key FROM {tabla} WHERE user_id IS NULL"


def sql_duplicados(tabla: str, columnas: tuple[str, ...] | None = None) -> str:
    """Grupos que violarían la PK ``columnas`` (por defecto, la nueva)."""
    cols = ", ".join(columnas or PK_NUEVA[tabla])
    return f"SELECT {cols}, count(*) FROM {tabla} GROUP BY {cols} HAVING count(*) > 1"


def _exigir_vacio(consulta: str, que: str) -> str:
    """Bloque ``DO`` que aborta la migración si ``consulta`` devuelve filas.

    El mensaje lleva la consulta tal cual: quien lo lea en el log del workflow
    tiene que poder copiarla y ver las filas sin abrir este fichero.
    """
    literal = consulta.replace("'", "''")
    return (
        "DO $$ DECLARE n bigint; BEGIN "
        f"SELECT count(*) INTO n FROM ({consulta}) AS q; "
        "IF n > 0 THEN RAISE EXCEPTION "
        f"'v135: % {que}. Nada se ha modificado. Revísalas con: {literal}', n; "
        "END IF; END $$"
    )


def _soltar_pk(tabla: str) -> None:
    """Borra la PK actual, se llame como se llame.

    ``user_profiles`` nació con el nombre por defecto de Postgres y
    ``radar_dismissals`` con ``pk_radar_dismissals``: se busca en el catálogo
    en vez de fiarse de ninguno de los dos.
    """
    op.execute(
        "DO $$ DECLARE pk text; BEGIN "
        "SELECT conname INTO pk FROM pg_constraint "
        f"WHERE conrelid = '{tabla}'::regclass AND contype = 'p'; "
        "IF pk IS NOT NULL THEN "
        f"EXECUTE format('ALTER TABLE {tabla} DROP CONSTRAINT %I', pk); "
        "END IF; END $$"
    )


def _recrear_fk(tabla: str, on_delete: str) -> None:
    fk = f"fk_{tabla}_user_id"
    op.execute(f"ALTER TABLE {tabla} DROP CONSTRAINT IF EXISTS {fk}")
    op.execute(
        f"ALTER TABLE {tabla} ADD CONSTRAINT {fk} "
        f"FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE {on_delete}"
    )


def upgrade() -> None:
    if not _is_postgres():
        return

    existentes = set(sa.inspect(op.get_bind()).get_table_names())
    presentes = [t for t in TABLAS if t in existentes]
    if not presentes:
        return

    op.execute(_CREAR_CLAVES)
    op.execute(_SEMBRAR_CLAVES)
    for tabla in presentes:
        op.execute(sql_backfill(tabla))

    # Todas las comprobaciones antes del primer DDL: si una tabla falla, la
    # otra no queda migrada a medias (aunque la transacción lo desharía igual,
    # así el mensaje sale antes de tomar ningún lock exclusivo).
    for tabla in presentes:
        op.execute(_exigir_vacio(sql_huerfanas(tabla), f"fila(s) de {tabla} sin user_id"))
        op.execute(
            _exigir_vacio(
                sql_duplicados(tabla),
                f"identidad(es) duplicada(s) en {tabla} por {', '.join(PK_NUEVA[tabla])}",
            )
        )

    for tabla in presentes:
        _soltar_pk(tabla)
        op.execute(f"ALTER TABLE {tabla} ALTER COLUMN user_id SET NOT NULL")
        op.execute(f"ALTER TABLE {tabla} ALTER COLUMN user_key DROP NOT NULL")
        op.execute(
            f"ALTER TABLE {tabla} ADD CONSTRAINT pk_{tabla} "
            f"PRIMARY KEY ({', '.join(PK_NUEVA[tabla])})"
        )
        # Transición (punto 4 del docstring): el ``ON CONFLICT`` del código de
        # la fase 2 necesita un índice único que case con sus columnas.
        op.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS uq_{tabla}_user_key "
            f"ON {tabla} ({', '.join(PK_VIEJA[tabla])})"
        )
        _recrear_fk(tabla, "CASCADE")


def downgrade() -> None:
    if not _is_postgres():
        return

    existentes = set(sa.inspect(op.get_bind()).get_table_names())
    presentes = [t for t in TABLAS if t in existentes]
    if not presentes:
        return

    # Las filas escritas en la fase 3 pueden no llevar clave: se deriva del
    # usuario, que es exactamente lo que la escritura de la fase 2 ponía.
    for tabla in presentes:
        op.execute(
            f"UPDATE {tabla} AS x SET user_key = {CLAVE_SQL} "
            "FROM users AS u WHERE x.user_key IS NULL AND x.user_id = u.id"
        )
    for tabla in presentes:
        op.execute(
            _exigir_vacio(
                f"SELECT user_id FROM {tabla} WHERE user_key IS NULL",
                f"fila(s) de {tabla} sin user_key",
            )
        )
        op.execute(
            _exigir_vacio(
                sql_duplicados(tabla, PK_VIEJA[tabla]),
                f"clave(s) duplicada(s) en {tabla} por {', '.join(PK_VIEJA[tabla])}",
            )
        )

    for tabla in presentes:
        op.execute(f"DROP INDEX IF EXISTS uq_{tabla}_user_key")
        _soltar_pk(tabla)
        op.execute(f"ALTER TABLE {tabla} ALTER COLUMN user_key SET NOT NULL")
        op.execute(f"ALTER TABLE {tabla} ALTER COLUMN user_id DROP NOT NULL")
        op.execute(
            f"ALTER TABLE {tabla} ADD CONSTRAINT pk_{tabla} "
            f"PRIMARY KEY ({', '.join(PK_VIEJA[tabla])})"
        )
        _recrear_fk(tabla, "SET NULL")
