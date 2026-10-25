"""v161: ``user_notifications`` se teclea por ``user_id`` (ADR-030 fase 3, segunda tanda).

Revision ID: v161_user_notifications_user_id_fase3
Revises: v160_fechas_ts_indices
Create Date: 2026-10-25

Qué corrige
-----------
v135 movió la PK de ``user_profiles`` y ``radar_dismissals`` a ``user_id``,
pero dejó ``user_notifications`` con su ``UNIQUE (user_key, licitacion_id,
type)`` de v48. Mientras esa fuera la única clave de la tabla:

* todo productor de alertas tenía que **derivar** la clave del correo
  (``user_key_from_email``) aunque ya tuviera el ``user_id`` del destinatario
  —``services/pursuit_awards.py``, ``services/pursuits.py``,
  ``services/deadline_reminders.py``—, y por eso seguían en el ratchet;
* ``radar_dismissals`` seguía escribiendo ``user_key`` solo para poder
  entregar sus recordatorios a esta tabla;
* la idempotencia tras un cambio de correo dependía de un ``SELECT`` previo
  del repositorio, no de la base: dos productores concurrentes podían colar
  la misma alerta bajo dos claves.

Lo que hace
-----------
1. **Backfill** de ``user_id`` en las filas que aún no lo tengan, con la misma
   derivación SQL de v129/v135 (repetida aquí porque una migración no importa
   de otra). En producción no queda ninguna (medido el 2026-10-25: 63 filas,
   0 sin id), pero recoge lo escrito sin id entre el despliegue y el
   ``apply``.
2. **Falla con ruido** si dos filas con ``user_id`` comparten
   ``(user_id, licitacion_id, type)``: son dos avisos del mismo expediente a la
   misma persona bajo claves de dos correos, y cuál se conserva es decisión
   humana. El mensaje lleva la consulta que las lista. Las filas con
   ``licitacion_id IS NULL`` no entran en la comprobación porque tampoco
   chocan en el índice (``NULL`` nunca es igual a ``NULL``).
3. ``UNIQUE INDEX uq_user_notifications_user_id (user_id, licitacion_id,
   type) WHERE user_id IS NOT NULL``: la identidad nueva la vigila la base.
   Parcial a propósito: las filas sin ``user_id`` —las que el backfill no
   resolvió— siguen tecleadas por ``user_key`` y no pueden tener dos claves
   iguales con ``NULL`` en la nueva.
4. ``user_key`` pasa a admitir ``NULL``. Desde esta revisión la puerta de
   escritura `insert_user_notification` (``db/notifications.py``) **no escribe la clave**
   cuando conoce el ``user_id``: una alerta nueva nace solo con el id. El
   ``UNIQUE (user_key, licitacion_id, type)`` de v48 **se conserva** y no es
   nostalgia: durante el despliegue el código de la fase 2 sigue haciendo
   ``ON CONFLICT (user_key, licitacion_id, type)`` y sin él Postgres rechaza
   el ``INSERT``; después sigue guardando las filas sin ``user_id``. Las
   claves ``NULL`` no chocan entre sí, así que no estorba a las nuevas.

Lo que NO hace
--------------
* No pone ``user_id NOT NULL``. Es la tanda que sí exige migrar antes todos
  los productores y los tests que hoy escriben solo con clave
  (``check_deadlines_and_notify(user_key)`` sobre favoritos sin id, las
  semillas de GDPR y de purga), y hacerlo a medias dejaría alertas sin
  escribir en silencio. Con el índice parcial la base ya garantiza lo que
  importa para el cambio de correo; el ``NOT NULL`` llega cuando
  ``watchlist_items`` deje de admitir filas sin id, que es de quien salen esos
  avisos.
* No toca ``notification_reads``, ``pending_digests`` ni
  ``user_event_prefs``: ningún productor deriva la clave para escribir en
  ellas, así que no sacan a nadie del ratchet; van con el mismo patrón cuando
  toquen.

Orden de despliegue
-------------------
**Esta revisión se aplica antes de desplegar el código.** El ``ON CONFLICT
(user_id, licitacion_id, type) WHERE user_id IS NOT NULL`` del repositorio
necesita el índice de aquí, y el ``INSERT`` sin ``user_key`` necesita que la
columna admita ``NULL``. El orden inverso (código viejo sobre schema nuevo) sí
funciona: el código viejo escribe las dos columnas y su arbitro sigue
existiendo (punto 4).

Antes del ``apply`` en producción: ``alembic upgrade
v161_user_notifications_user_id_fase3 --sql`` para revisar el DDL, y
``sql_duplicados()`` a mano para saber si el ``RAISE`` va a saltar.

Downgrade: recupera ``user_key`` en las filas escritas sin ella derivándola de
``users`` (igual que v135), falla si alguna queda sin clave o dos colisionan,
devuelve ``NOT NULL`` a la columna y quita el índice nuevo.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v161_user_notifications_user_id_fase3"
down_revision: str | Sequence[str] | None = "v160_fechas_ts_indices"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLA = "user_notifications"

#: Columnas de la identidad nueva, en el orden del índice.
CLAVE_NUEVA: tuple[str, ...] = ("user_id", "licitacion_id", "type")
CLAVE_VIEJA: tuple[str, ...] = ("user_key", "licitacion_id", "type")

INDICE_NUEVO = "uq_user_notifications_user_id"

#: Derivación de ``user_key`` en SQL sobre la fila ``u`` de ``users``: la
#: misma transcripción de ``shared.identity.user_key_from_email`` que v129.
CLAVE_SQL = (
    "substr(encode(sha256(convert_to(lower(btrim("
    "COALESCE(NULLIF(u.email, ''), 'user:' || u.id::text), E' \\t\\r\\n')), 'UTF8')), "
    "'hex'), 1, 16)"
)

_CREAR_CLAVES = (
    "CREATE TEMPORARY TABLE v161_claves ("
    "user_key TEXT PRIMARY KEY, user_id INTEGER NOT NULL) ON COMMIT DROP"
)

_SEMBRAR_CLAVES = (
    "INSERT INTO v161_claves (user_key, user_id) "
    f"SELECT {CLAVE_SQL}, u.id FROM users u "
    "ON CONFLICT (user_key) DO NOTHING"
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def sql_backfill() -> str:
    """``UPDATE`` que resuelve ``user_id`` por ``user_key`` (igual que v129)."""
    return (
        f"UPDATE {TABLA} AS x SET user_id = k.user_id "
        "FROM v161_claves AS k "
        "WHERE x.user_id IS NULL AND x.user_key = k.user_key"
    )


def sql_duplicados(columnas: tuple[str, ...] | None = None) -> str:
    """Grupos que violarían el índice único por ``columnas`` (por defecto, la nueva).

    Solo cuentan las filas que el índice compara: con la primera columna de la
    clave resuelta y con ``licitacion_id`` (dos ``NULL`` nunca chocan).
    """
    cols = columnas or CLAVE_NUEVA
    lista = ", ".join(cols)
    return (
        f"SELECT {lista}, count(*) FROM {TABLA} "
        f"WHERE {cols[0]} IS NOT NULL AND licitacion_id IS NOT NULL "
        f"GROUP BY {lista} HAVING count(*) > 1"
    )


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
        f"'v161: % {que}. Nada se ha modificado. Revísalas con: {literal}', n; "
        "END IF; END $$"
    )


def upgrade() -> None:
    if not _is_postgres():
        return
    if TABLA not in set(sa.inspect(op.get_bind()).get_table_names()):
        return

    op.execute(_CREAR_CLAVES)
    op.execute(_SEMBRAR_CLAVES)
    op.execute(sql_backfill())

    # La comprobación va antes del primer DDL: el mensaje sale sin haber
    # tomado ningún lock exclusivo.
    op.execute(
        _exigir_vacio(
            sql_duplicados(),
            f"identidad(es) duplicada(s) en {TABLA} por {', '.join(CLAVE_NUEVA)}",
        )
    )

    op.execute(f"ALTER TABLE {TABLA} ALTER COLUMN user_key DROP NOT NULL")
    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {INDICE_NUEVO} "
        f"ON {TABLA} ({', '.join(CLAVE_NUEVA)}) WHERE user_id IS NOT NULL"
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    if TABLA not in set(sa.inspect(op.get_bind()).get_table_names()):
        return

    # Las filas de esta fase no llevan clave: se deriva del usuario, que es
    # exactamente lo que la escritura de la fase 2 ponía.
    op.execute(
        f"UPDATE {TABLA} AS x SET user_key = {CLAVE_SQL} "
        "FROM users AS u WHERE x.user_key IS NULL AND x.user_id = u.id"
    )
    op.execute(
        _exigir_vacio(
            f"SELECT id FROM {TABLA} WHERE user_key IS NULL",
            f"fila(s) de {TABLA} sin user_key",
        )
    )
    op.execute(
        _exigir_vacio(
            sql_duplicados(CLAVE_VIEJA),
            f"clave(s) duplicada(s) en {TABLA} por {', '.join(CLAVE_VIEJA)}",
        )
    )

    op.execute(f"DROP INDEX IF EXISTS {INDICE_NUEVO}")
    op.execute(f"ALTER TABLE {TABLA} ALTER COLUMN user_key SET NOT NULL")
