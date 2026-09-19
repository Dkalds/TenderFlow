"""Persistencia de los descartes del Radar (tabla ``radar_dismissals``).

El Radar guardaba los descartes en ``React.useState``, así que el triaje se
perdía al recargar (invariante 2 de ``docs/frontend-data-invariants.md``: el
estado de usuario es server-side). Este módulo es su respaldo.

Desde ``v103`` un descarte puede **caducar** (F5.6): ``hasta`` dice cuándo
deja de aplicar y ``accion`` si el usuario silenció («no me interesa por
ahora») o pospuso («recuérdamelo»). ``hasta IS NULL`` sigue siendo el descarte
permanente de siempre, que es lo que tienen todas las filas anteriores.

**Todas** las consultas filtran por identidad. La tabla es user-scoped y el
repositorio se defiende solo: no delega el control de propiedad en la ruta que
lo llame, que es justo el hueco de aislamiento que
``tests/test_user_key_sql_isolation.py`` audita en ``db/watchlist.py``.

Desde v129 (ADR-030 fase 2) la fila lleva ``user_id`` junto a ``user_key`` y
la lectura es dual (ver ``db/repositories/watchlist.py``). Desde v135 (fase 3)
la PK es ``(user_id, id_externo)``: :func:`add` exige ``user_id`` y es un
único upsert por esa clave. La lectura dual se conserva porque no cuesta nada
y sigue sirviendo a quien llame sin id las filas escritas antes.
"""

from __future__ import annotations

from typing import Any, Final, Literal

from db.database import connect, connect_read

#: Qué puede pedir el usuario al quitar una señal de la bandeja. ``descartar``
#: es el permanente de v76 y no escribe ``accion``; los otros dos caducan.
AccionDescarte = Literal["descartar", "silenciar", "posponer"]

#: Predicado «este descarte sigue en pie». Se escribe una sola vez porque lo
#: comparten la lectura del Radar y la del recordatorio, y dos grafías del
#: mismo juicio es como el resumen acabó contradiciendo al Radar
#: (ver ``shared/estados.py``, mismo argumento).
VIGENTE_SQL: Final = "(hasta IS NULL OR hasta > now())"

#: Predicado de identidad dual. Parámetros: ``(user_id, user_key, user_id)``.
_IDENT = "(user_id = %s OR (user_key = %s AND (user_id IS NULL OR %s::int IS NULL)))"


def add(
    user_key: str,
    id_externo: str,
    *,
    score: int | None = None,
    banda: str | None = None,
    hasta: str | None = None,
    accion: str | None = None,
    organization_id: int | None = None,
    user_id: int,
) -> None:
    """Marca una licitación como descartada por el usuario.

    ``score`` y ``banda`` son la puntuación que el usuario tenía **delante** al
    descartar, no la de ahora. Se guardan porque son irrecuperables: el score se
    calcula en vivo sobre el universo del día y los pesos del perfil, así que
    preguntárselo mañana al motor daría otro número (revisión ``v93``). Son
    opcionales para que un cliente que no los mande siga pudiendo descartar: el
    triaje no puede depender de la telemetría.

    ``hasta`` (ISO-8601) y ``accion`` implementan silenciar y posponer (F5.6).

    **Aquí sí se reescribe** una fila existente, al revés que el ``DO NOTHING``
    original. El motivo del ``DO NOTHING`` era conservar el score del primer
    descarte —la puntuación que motivó la decisión— y eso se mantiene:
    ``score`` y ``banda`` sólo se escriben si la fila no los tenía
    (``COALESCE`` sobre el valor viejo). Lo que sí manda es la **última**
    decisión de vigencia: quien silencia treinta días algo que había
    descartado, o vuelve a posponer lo que ya venció, está diciendo cuándo
    quiere volver a verlo, y un ``DO NOTHING`` lo ignoraría en silencio.

    Desde v135 (ADR-030 fase 3) la PK es ``(user_id, id_externo)``, así que
    ``user_id`` es obligatorio y un solo ``ON CONFLICT`` encuentra el descarte
    aunque se hubiera escrito bajo otra clave: ya no hace falta localizarlo
    antes por identidad dual. ``user_key`` se sigue escribiendo —y la de la
    fila existente no se toca— porque el recordatorio de :func:`pospuestos_vencidos`
    la entrega a ``user_notifications``, que todavía se teclea por ella.
    """
    with connect() as c:
        c.execute(
            "INSERT INTO radar_dismissals "
            "  (user_key, user_id, id_externo, score, banda, hasta, accion, organization_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (user_id, id_externo) DO UPDATE SET "
            "  score = COALESCE(radar_dismissals.score, EXCLUDED.score), "
            "  banda = COALESCE(radar_dismissals.banda, EXCLUDED.banda), "
            "  hasta = EXCLUDED.hasta, "
            "  accion = EXCLUDED.accion, "
            "  organization_id = COALESCE("
            "    EXCLUDED.organization_id, radar_dismissals.organization_id)",
            (user_key, user_id, id_externo, score, banda, hasta, accion, organization_id),
        )

    # Escritura doble hacia `follows` (ADR-031 §B, fase aditiva): un descarte es
    # seguir con signo negativo, y es una de las tres tablas que alimentan la
    # unificada. Va FUERA del `with`, con la fila ya confirmada, y no lanza
    # nunca (ver `db/repositories/follows.py::registrar`): mientras `follows`
    # sea una copia, un fallo suyo no puede impedir que el usuario descarte.
    from db.repositories import follows as _follows

    _follows.registrar(
        user_key=user_key,
        user_id=user_id,
        organization_id=organization_id,
        target_type="licitacion",
        target_id=id_externo,
        kind="descartar",
        hasta=hasta,
    )


def remove(user_key: str, id_externo: str, *, user_id: int | None = None) -> bool:
    """Deshace un descarte. ``True`` si había algo que deshacer."""
    from db.repositories import follows as _follows

    with connect() as c:
        cur = c.execute(
            f"DELETE FROM radar_dismissals WHERE {_IDENT} AND id_externo = %s",
            (user_id, user_key, user_id, id_externo),
        )
        borrado = bool(cur.rowcount > 0)

    # Se limpia `follows` aunque no hubiera nada que borrar aquí: si las dos
    # tablas divergieron, esta es la ocasión de volver a cuadrarlas, y dejar un
    # descarte huérfano en `follows` sería peor que el no-op.
    _follows.olvidar(
        user_key=user_key,
        user_id=user_id,
        target_type="licitacion",
        target_id=id_externo,
        kind="descartar",
    )
    return borrado


def delete_all_for_user(user_key: str, *, user_id: int | None = None) -> int:
    """Borra todos los descartes del usuario, vigentes o caducados (GDPR).

    Son dato personal (ADR-030 §D) y se van con la persona. Devuelve filas
    borradas.
    """
    with connect() as c:
        cur = c.execute(
            f"DELETE FROM radar_dismissals WHERE {_IDENT}",
            (user_id, user_key, user_id),
        )
        return int(cur.rowcount)


def list_ids(user_key: str, *, user_id: int | None = None) -> list[str]:
    """``id_externo`` descartados **y vigentes**, recientes primero.

    Un descarte caducado no se borra: se deja de aplicar. Conservarlo es lo que
    permite responder «esto ya lo silenciaste dos veces» y lo que hace que la
    reaparición sea un hecho observable en la tabla y no un borrado que nadie
    puede auditar. La limpieza, si algún día hace falta, es retención — no
    lectura.
    """
    with connect_read() as c:
        cur = c.execute(
            "SELECT DISTINCT ON (id_externo) id_externo, created_at FROM radar_dismissals "
            f"WHERE {_IDENT} AND {VIGENTE_SQL} "
            "ORDER BY id_externo, created_at DESC",
            (user_id, user_key, user_id),
        )
        filas = sorted(cur.fetchall(), key=lambda row: row[1], reverse=True)
        return [str(row[0]) for row in filas]


def list_detalle(user_key: str, *, user_id: int | None = None) -> list[dict[str, Any]]:
    """Los descartes vigentes con su fecha y acción, para pintarlos.

    El Radar necesita distinguir «silenciada hasta el 6 de octubre» de
    «descartada», y con :func:`list_ids` no puede: sólo devuelve ids.

    ``DISTINCT ON (id_externo)``: un usuario que descartó lo mismo bajo dos
    claves (antes de v129) tiene dos filas y un solo descarte.
    """
    with connect_read() as c:
        cur = c.execute(
            "SELECT DISTINCT ON (id_externo) id_externo, hasta, accion, score, banda, "
            "created_at FROM radar_dismissals "
            f"WHERE {_IDENT} AND {VIGENTE_SQL} "
            "ORDER BY id_externo, created_at DESC",
            (user_id, user_key, user_id),
        )
        filas = sorted(cur.fetchall(), key=lambda row: row[5], reverse=True)
        return [
            {
                "id_externo": str(row[0]),
                "hasta": row[1].isoformat() if row[1] is not None else None,
                "accion": row[2],
                "score": row[3],
                "banda": row[4],
            }
            for row in filas
        ]


def pospuestos_vencidos(*, desde_iso: str) -> list[dict[str, Any]]:
    """Aplazamientos que han vencido desde ``desde_iso`` y aún no se avisaron.

    Es lo que consume el job de recordatorios (F5.6: «el recordatorio llega
    como alerta en la fecha elegida»). Se acota por ventana inferior y no se
    marca nada aquí: la idempotencia la da la clave
    ``UNIQUE(user_key, licitacion_id, type)`` de ``user_notifications``, igual
    que en el resto de productores de alertas. Sin esa ventana, cada pasada
    del job recorrería todos los aplazamientos vencidos de la historia para
    que el ``ON CONFLICT`` los descartara uno a uno.

    Sólo ``accion = 'posponer'``: silenciar es «no me lo enseñes», y avisar de
    que ha vuelto a la bandeja sería exactamente lo contrario de lo que el
    usuario pidió.
    """
    with connect_read() as c:
        cur = c.execute(
            "SELECT user_key, id_externo, hasta, organization_id, user_id "
            "FROM radar_dismissals "
            "WHERE accion = 'posponer' AND hasta IS NOT NULL "
            "  AND hasta <= now() AND hasta >= %s "
            "ORDER BY hasta",
            (desde_iso,),
        )
        return [
            {
                "user_key": str(row[0]),
                "id_externo": str(row[1]),
                "hasta": row[2].isoformat() if row[2] is not None else None,
                "organization_id": int(row[3]) if row[3] is not None else None,
                "user_id": int(row[4]) if row[4] is not None else None,
            }
            for row in cur.fetchall()
        ]
