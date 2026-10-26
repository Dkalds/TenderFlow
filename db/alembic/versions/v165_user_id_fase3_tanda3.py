"""v165: ``notification_reads``, ``user_event_prefs`` y ``saved_filters`` se teclean por ``user_id``.

Revision ID: v165_user_id_fase3_tanda3
Revises: v163_identidad_placsp_fase_a
Create Date: 2026-10-26

ADR-030 fase 3, tercera tanda. Mismo patrón que v162 con ``user_notifications``.

Qué corrige
-----------
Las tres tablas guardan dato personal (marcas de lectura y «última visita» de
la campana, preferencia de correo por tipo de evento, vistas guardadas) y su
única clave de unicidad sigue siendo la de antes de v129, por la clave derivada
del correo:

* ``notification_reads``  → ``UNIQUE (user_key, notification_id)`` (v51)
* ``user_event_prefs``    → ``UNIQUE (user_key, event_type)`` (v107)
* ``saved_filters``       → ``UNIQUE (user_key, name)`` (v51)

Mientras sea así, sus escritores tienen que seguir escribiendo ``user_key``
aunque conozcan el ``user_id``, y la unicidad tras un cambio de correo depende
de un ``UPDATE`` previo por identidad dual en el repositorio, no de la base.

Lo que hace
-----------
1. **Backfill** de ``user_id`` por ``user_key`` en las tres, con la derivación
   SQL de v129 (repetida porque una migración no importa de otra). En
   producción no queda ninguna fila sin id (medido el 2026-10-26: 1, 0 y 1
   filas en total), pero recoge lo escrito sin id hasta el ``apply``.
2. **Deduplica** ``notification_reads`` por ``(user_id, notification_id)``:
   dos marcas del mismo usuario sobre la misma notificación bajo dos claves
   dicen lo mismo («leída»). Se conserva la de ``read_at`` más reciente, así
   que ``MAX(read_at)`` —la «última visita» de ``get_last_seen_ts``— no cambia
   y ``get_unread_ids`` tampoco. No hay decisión humana que tomar.
3. **Falla con ruido** si ``user_event_prefs`` o ``saved_filters`` tienen dos
   filas con el mismo ``(user_id, event_type)`` / ``(user_id, name)``: dos
   preferencias distintas o dos vistas homónimas de la misma persona bajo dos
   correos, y cuál se conserva sí es decisión humana. El mensaje lleva la
   consulta que las lista. La comprobación va antes del primer DDL.
4. ``user_key`` pasa a admitir ``NULL`` en las tres, y cada una recibe un
   ``UNIQUE INDEX uq_<tabla>_user_id (user_id, <columna>) WHERE user_id IS NOT
   NULL``. Parcial por lo mismo que en v162: las filas sin ``user_id`` siguen
   tecleadas por la clave. El ``UNIQUE`` por ``user_key`` **se conserva**: es
   el árbitro del ``ON CONFLICT`` del código anterior durante el despliegue y,
   después, el de las filas sin id. Las claves ``NULL`` no chocan entre sí.

Desde esta revisión ``db/notifications.py`` (``mark_read``, ``mark_all_read``,
``marcar_visita``, ``guardar_modo_email``) y ``db/saved_filters.py``
(``save_filter``) no escriben la clave cuando conocen el id.

Lo que NO hace
--------------
* No pone ``user_id NOT NULL``: una API key sin usuario escribe todavía sólo
  con clave (``api/routes/notifications.py`` y ``saved_filters.py`` pasan
  ``user_id=None`` cuando el principal no lo tiene).
* No toca ``follows`` ni ``pending_digests``. ``follows`` se escribe en doble
  desde ``watchlist_items``/``watchlist_empresas``/``radar_dismissals`` y se
  cruza con ellas por ``user_key`` (las lecturas ``*_desde_follows`` y la
  paridad de ``scripts/check_follows_paridad.py``, que es el gate de su fase
  2): dejar de escribir la clave ahí rompe esos cruces hasta que las tablas de
  origen se tecleen por id. ``pending_digests`` no tiene clave de usuario que
  re-teclear (su ``UNIQUE`` es ``(entry_id, licitacion_id)``) y su
  ``user_key`` alimenta el enlace de baja del correo y el cruce con
  ``watchlist_rules``: va con ``watchlist_*``.

Orden de despliegue
-------------------
**Esta revisión se aplica antes de desplegar el código.** El ``ON CONFLICT
(user_id, …) WHERE user_id IS NOT NULL`` necesita los índices de aquí, y el
``INSERT`` sin ``user_key`` que la columna admita ``NULL``. El orden inverso
(código viejo sobre schema nuevo) funciona: el código viejo escribe las dos
columnas y su árbitro sigue existiendo.

Antes del ``apply`` en producción: ``alembic upgrade v165_user_id_fase3_tanda3
--sql`` para revisar el DDL, y ``sql_duplicados(tabla)`` a mano para saber si
el ``RAISE`` va a saltar.

Downgrade: recupera ``user_key`` en las filas escritas sin ella derivándola de
``users``, falla si alguna queda sin clave o dos colisionan por la clave vieja,
quita los índices nuevos y devuelve ``NOT NULL`` a la columna.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v165_user_id_fase3_tanda3"
down_revision: str | Sequence[str] | None = "v163_identidad_placsp_fase_a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: ``tabla → columna`` que acompaña a la identidad en su clave de unicidad.
TABLAS: dict[str, str] = {
    "notification_reads": "notification_id",
    "user_event_prefs": "event_type",
    "saved_filters": "name",
}

#: Tablas cuyos duplicados por la identidad nueva se fusionan solos (punto 2
#: del docstring); en las demás abortan la migración.
SE_DEDUPLICAN: frozenset[str] = frozenset({"notification_reads"})

#: Derivación de ``user_key`` en SQL sobre la fila ``u`` de ``users``: la
#: misma transcripción de ``shared.identity.user_key_from_email`` que v129.
CLAVE_SQL = (
    "substr(encode(sha256(convert_to(lower(btrim("
    "COALESCE(NULLIF(u.email, ''), 'user:' || u.id::text), E' \\t\\r\\n')), 'UTF8')), "
    "'hex'), 1, 16)"
)

_CREAR_CLAVES = (
    "CREATE TEMPORARY TABLE v165_claves ("
    "user_key TEXT PRIMARY KEY, user_id INTEGER NOT NULL) ON COMMIT DROP"
)

_SEMBRAR_CLAVES = (
    "INSERT INTO v165_claves (user_key, user_id) "
    f"SELECT {CLAVE_SQL}, u.id FROM users u "
    "ON CONFLICT (user_key) DO NOTHING"
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def indice(tabla: str) -> str:
    """Nombre del índice único parcial por ``user_id`` de ``tabla``."""
    return f"uq_{tabla}_user_id"


def sql_backfill(tabla: str) -> str:
    """``UPDATE`` que resuelve ``user_id`` por ``user_key`` (igual que v129)."""
    return (
        f"UPDATE {tabla} AS x SET user_id = k.user_id "
        "FROM v165_claves AS k "
        "WHERE x.user_id IS NULL AND x.user_key = k.user_key"
    )


def sql_deduplicar_lecturas() -> str:
    """Borra las marcas repetidas por ``(user_id, notification_id)``.

    Se queda la de ``read_at`` más reciente (y, empatadas, la de ``id`` mayor):
    ``read_at`` es texto ISO y se compara igual que lo compara ``MAX(read_at)``
    en ``db.notifications.get_last_seen_ts``, así que la última visita no se
    mueve.
    """
    return (
        "DELETE FROM notification_reads AS a USING notification_reads AS b "
        "WHERE a.user_id IS NOT NULL AND a.user_id = b.user_id "
        "AND a.notification_id = b.notification_id "
        "AND (a.read_at, a.id) < (b.read_at, b.id)"
    )


def sql_duplicados(tabla: str, identidad: str = "user_id") -> str:
    """Grupos que violarían el índice único de ``tabla`` por ``identidad``.

    Sólo cuentan las filas con la identidad resuelta: dos ``NULL`` nunca chocan.
    La otra columna de la clave es ``NOT NULL`` en las tres tablas.
    """
    lista = f"{identidad}, {TABLAS[tabla]}"
    return (
        f"SELECT {lista}, count(*) FROM {tabla} "
        f"WHERE {identidad} IS NOT NULL "
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
        f"'v165: % {que}. Nada se ha modificado. Revísalas con: {literal}', n; "
        "END IF; END $$"
    )


def _presentes() -> list[str]:
    existentes = set(sa.inspect(op.get_bind()).get_table_names())
    return [t for t in TABLAS if t in existentes]


def upgrade() -> None:
    if not _is_postgres():
        return
    tablas = _presentes()
    if not tablas:
        return

    op.execute(_CREAR_CLAVES)
    op.execute(_SEMBRAR_CLAVES)
    for tabla in tablas:
        op.execute(sql_backfill(tabla))
    for tabla in tablas:
        if tabla in SE_DEDUPLICAN:
            op.execute(sql_deduplicar_lecturas())

    # Todas las comprobaciones antes del primer DDL: si una salta, el mensaje
    # sale sin haber tomado ningún lock exclusivo y sin dejar media tanda.
    for tabla in tablas:
        op.execute(
            _exigir_vacio(
                sql_duplicados(tabla),
                f"identidad(es) duplicada(s) en {tabla} por user_id, {TABLAS[tabla]}",
            )
        )

    for tabla in tablas:
        op.execute(f"ALTER TABLE {tabla} ALTER COLUMN user_key DROP NOT NULL")
        op.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {indice(tabla)} "
            f"ON {tabla} (user_id, {TABLAS[tabla]}) WHERE user_id IS NOT NULL"
        )


def downgrade() -> None:
    if not _is_postgres():
        return
    tablas = _presentes()

    # Las filas de esta fase no llevan clave: se deriva del usuario, que es
    # exactamente lo que la escritura de la fase 2 ponía.
    for tabla in tablas:
        op.execute(
            f"UPDATE {tabla} AS x SET user_key = {CLAVE_SQL} "
            "FROM users AS u WHERE x.user_key IS NULL AND x.user_id = u.id"
        )
    for tabla in tablas:
        op.execute(
            _exigir_vacio(
                f"SELECT id FROM {tabla} WHERE user_key IS NULL",
                f"fila(s) de {tabla} sin user_key",
            )
        )
        op.execute(
            _exigir_vacio(
                sql_duplicados(tabla, "user_key"),
                f"clave(s) duplicada(s) en {tabla} por user_key, {TABLAS[tabla]}",
            )
        )

    for tabla in tablas:
        op.execute(f"DROP INDEX IF EXISTS {indice(tabla)}")
        op.execute(f"ALTER TABLE {tabla} ALTER COLUMN user_key SET NOT NULL")
