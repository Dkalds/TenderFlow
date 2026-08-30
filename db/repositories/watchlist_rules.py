"""Repository de conteo de matches de reglas de watchlist.

Existe por una razón muy concreta: el listado de reglas (``GET
/api/v1/watchlist/rules``) necesita un número por regla para el badge de la
tarjeta, y el conteo exacto no es pagable. Un ``SELECT COUNT(*) FROM
licitaciones WHERE titulo ILIKE '%kw%' OR descripcion ILIKE '%kw%'`` recorre
~1,6M filas de forma secuencial —``descripcion`` no tiene índice trigram— y el
listado lo hacía **una vez por regla**, cada una con su propia conexión del
pool. Con N reglas: N escaneos completos y N conexiones dentro de una sola
petición HTTP, contra un ``statement_timeout`` de 30 s.

La respuesta es acotar: se cuenta sobre un subselect con ``LIMIT``
(:data:`MATCH_COUNT_CAP`), de modo que el planner puede parar en cuanto reúne
esas filas en vez de agotar la tabla, y todas las reglas comparten **una** sola
conexión. El precio es que el número deja de ser exacto por encima del tope; la
UI lo muestra como «999+», que es toda la precisión que una tarjeta puede
aprovechar (el conteo exacto sigue disponible en el detalle de la regla).

ADR-022: el SQL vive en ``db/``. Las cláusulas del filtro las construye
``services.watchlist_rules._rule_clauses`` sobre la misma tabla de
``db.models``; aquí solo se envuelven en la forma acotada y se ejecutan.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, and_, func, literal, select, text

from db.database import connect_read
from db.models import compile_query, licitaciones
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)

# Techo del conteo. 1.000 es suficiente para que el badge distinga «pocas»,
# «bastantes» y «demasiadas»; por encima, el usuario necesita afinar la regla,
# no un dígito más.
MATCH_COUNT_CAP = 1000

#: Tipo de notificación in-app que escribe el job de alertas. Es la mitad de la
#: clave de deduplicación; la otra mitad son ``user_key`` y ``licitacion_id``.
TIPO_NOTIFICACION_REGLA = "rule_match"


def _bounded_count_stmt(clauses: Sequence[Any]) -> Select[tuple[int]]:
    """``SELECT count(*) FROM (SELECT 1 FROM licitaciones WHERE … LIMIT cap)``.

    El ``LIMIT`` va dentro del subselect a propósito: puesto fuera limitaría la
    fila del resultado (siempre una) y no ahorraría ni un tuple del escaneo.
    """
    inner = select(literal(1)).select_from(licitaciones)
    if clauses:
        inner = inner.where(and_(*clauses))
    return select(func.count()).select_from(inner.limit(MATCH_COUNT_CAP).subquery())


def bounded_match_counts(clauses_per_rule: Sequence[Sequence[Any]]) -> list[int]:
    """Conteo acotado de cada regla, todas sobre la MISMA conexión.

    Devuelve una lista alineada con ``clauses_per_rule``. Cada valor está
    saturado en :data:`MATCH_COUNT_CAP`: alcanzarlo significa «al menos tantas»,
    no «exactamente tantas».
    """
    if not clauses_per_rule:
        # Un usuario sin reglas no debe llegar a pedir conexión al pool.
        return []
    counts: list[int] = []
    with connect_read() as c:
        for clauses in clauses_per_rule:
            sql, params = compile_query(_bounded_count_stmt(clauses))
            row = c.execute(sql, params).fetchone()
            counts.append(int(row[0]) if row else 0)
    return counts


# ── Matches todavía no notificados ────────────────────────────────────────────
#
# El job de alertas (``scheduler/watchlist_rules_alerts.py``) necesita «lo nuevo
# desde la última vez». Durante meses eso se resolvió con un corte temporal
# solo, y el corte solo no puede ser correcto: la ventana avanza en cada
# evaluación —haya o no matches— mientras la columna de publicación tiene
# granularidad de día, así que en cuanto una regla se evalúa el día D, todo lo
# publicado ese mismo día queda fuera de su próxima ventana para siempre. Con
# el carril diario corriendo a las 00:0x UTC, el día D no ha publicado nada
# todavía cuando la ventana se cierra sobre él: la regla no volvía a disparar
# nunca más después de su primera evaluación.
#
# La corrección tiene dos mitades y hacen falta las dos:
#
#   1. El corte pasa a ser **inclusivo** (``>=``) y con unos días de gracia
#      hacia atrás, para que reingestas tardías entren en la ventana.
#   2. Como consecuencia la ventana **se solapa a propósito**, así que quien
#      decide qué es «nuevo» ya no puede ser la fecha: es el anti-join contra
#      ``user_notifications``, que es además la misma verdad que ya imponía el
#      ``UNIQUE(user_key, licitacion_id, type)`` de la revisión v48. Antes esa
#      unicidad solo actuaba en el INSERT, es decir demasiado tarde: las filas
#      ya notificadas gastaban el ``LIMIT`` y desplazaban a las que sí eran
#      nuevas.
#
# El anti-join va por ``user_key`` y no por ``rule_id`` a propósito: replica
# exactamente la clave del índice único, así que no cambia qué se notifica —
# solo evita que el tope se gaste en filas cuyo INSERT iba a ser un no-op.


def _sin_notificar(user_key: str) -> Any:
    """``NOT EXISTS`` contra las notificaciones ya escritas para ese usuario.

    Se escribe con ``text()`` y no con una tabla de ``db.models`` porque
    ``user_notifications`` no está declarada allí y declararla entera para dos
    columnas de un anti-join sería más superficie de la que resuelve. Los
    valores viajan como bind params, nunca interpolados.
    """
    return text(
        "NOT EXISTS ("
        " SELECT 1 FROM user_notifications n"
        " WHERE n.user_key = :wr_user_key"
        "   AND n.type = :wr_tipo"
        "   AND n.licitacion_id = licitaciones.id_externo"
        ")"
    ).bindparams(wr_user_key=user_key, wr_tipo=TIPO_NOTIFICACION_REGLA)


def _stmt_matches(
    clauses: Sequence[Any],
    columns: Sequence[Any],
    *,
    desde: str | None,
    limit: int,
    user_key: str | None,
) -> Select[Any]:
    condiciones = list(clauses)
    if desde:
        # Inclusivo: ver el bloque de arriba. La deduplicación la hace el
        # anti-join, no el operador de comparación.
        condiciones.append(licitaciones.c.fecha_publicacion >= desde)
    if user_key is not None:
        condiciones.append(_sin_notificar(user_key))
    stmt = select(*columns).select_from(licitaciones)
    if condiciones:
        stmt = stmt.where(and_(*condiciones))
    return stmt.order_by(licitaciones.c.fecha_publicacion.desc()).limit(limit)


def _tabla_ausente(exc: Exception) -> bool:
    """¿El error es «no existe user_notifications» y no otra cosa?

    Mismo criterio que ``scheduler/healthcheck.py``: cada motor y cada locale
    redacta el mensaje a su manera, y tragarse cualquier excepción convertiría
    un fallo real de BD en «cero matches», que es justo el modo de fallo mudo
    que esta función existe para eliminar.
    """
    mensaje = str(exc).lower()
    return "user_notifications" in mensaje and (
        "does not exist" in mensaje or "no existe" in mensaje or "no such table" in mensaje
    )


def matches_pendientes(
    clauses: Sequence[Any],
    columns: Sequence[Any],
    *,
    desde: str | None,
    limit: int,
    user_key: str | None = None,
) -> list[dict[str, Any]]:
    """Matches de una regla que todavía no se han notificado a ``user_key``.

    Con ``user_key=None`` se comporta como un listado con corte temporal
    inclusivo y sin anti-join: es lo que consumen la vista previa y los tests
    que no ejercen el job.

    Las cláusulas del filtro las construye ``services.watchlist_rules`` sobre la
    misma tabla de ``db.models``; aquí se componen y se ejecutan (ADR-022).
    """
    stmt = _stmt_matches(clauses, columns, desde=desde, limit=limit, user_key=user_key)
    sql, params = compile_query(stmt)
    with connect_read() as c:
        try:
            return rows_to_dicts(c.execute(sql, params))
        except Exception as exc:
            if user_key is None or not _tabla_ausente(exc):
                raise
    # BD legacy sin la revisión v48: se degrada al listado sin anti-join en vez
    # de dejar al usuario sin alertas. El INSERT posterior ya tolera lo mismo.
    log.warning("watchlist_matches_sin_tabla_notificaciones")
    sql, params = compile_query(
        _stmt_matches(clauses, columns, desde=desde, limit=limit, user_key=None)
    )
    with connect_read() as c:
        return rows_to_dicts(c.execute(sql, params))
