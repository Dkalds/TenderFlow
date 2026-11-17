"""Persistencia de ``contrato_eventos`` (eventos del ciclo de vida del contrato).

La tabla la deriva ``services/contract_events.py`` de ``licitaciones_history``
(Fase 4): la clasificación de cada cambio vive allí; aquí, el SQL con el que
lee el historial y escribe los eventos —dentro de la transacción que abre
:func:`en_transaccion`— y las lecturas del feed y de la línea de tiempo.
ADR-022: todo el SQL vive en ``db/``.

Módulo de funciones, no clase: es el mismo estrato que ``db/repositories/*``
(AGENTS.md §3.10), y las consultas de esta tabla no comparten estado ni
filtros que justifiquen agruparlas en un repository.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any, TypedDict, TypeVar, cast

from db.database import connect, connect_read
from db.repositories.aggregates import LicitacionesFilters, build_licitaciones_where
from db.repositories.base import rows_to_dicts

if TYPE_CHECKING:
    from collections.abc import Callable

    from db.connection import _PgConnAdapter

T = TypeVar("T")


class FilaHistorialPendiente(TypedDict):
    """Una fila de ``licitaciones_history`` por derivar (:func:`historial_pendiente`)."""

    id: int
    id_externo: str
    captured_at: object  # texto ISO o timestamp según la revisión; se usa con str()[:10]
    snapshot_json: str
    changed_fields: str | None


#: Columnas de la fila actual de ``licitaciones`` que hacen de estado «después»
#: del último cambio de un expediente. Además de los cinco campos de contrato
#: van ``fecha_limite``, ``cpv``, ``url`` y ``titulo``: el aviso al seguidor
#: (S4.5) los necesita para decir qué cambió y a qué.
COLUMNAS_ESTADO_ACTUAL: tuple[str, ...] = (
    "estado",
    "importe",
    "fecha_fin",
    "duracion_valor",
    "duracion_unidad",
    "fecha_limite",
    "cpv",
    "url",
    "titulo",
)


def en_transaccion(fn: Callable[[_PgConnAdapter], T]) -> T:
    """Corre ``fn(conn)`` en una única transacción de escritura y devuelve su resultado.

    Commit al salir; si ``fn`` lanza, rollback y la excepción sigue su curso.
    Es la frontera con la que ``services.contract_events`` deriva un lote de
    historial —eventos y avisos del outbox juntos— sin abrir conexiones fuera
    de ``db/`` (ADR-022), como ``db.empresas.en_transaccion`` para la
    resolución de empresas. ``fn`` no usa la conexión: solo la reenvía a las
    funciones de ``db/`` que la aceptan.
    """
    with connect() as conn:
        return fn(conn)


def historial_pendiente(
    conn: _PgConnAdapter, after_id: int, limit: int
) -> list[FilaHistorialPendiente]:
    """Filas de ``licitaciones_history`` con ``id > after_id``, en orden de id."""
    filas = rows_to_dicts(
        conn.execute(
            "SELECT id, id_externo, captured_at, snapshot_json, changed_fields "
            "FROM licitaciones_history WHERE id > %s ORDER BY id LIMIT %s",
            (after_id, limit),
        )
    )
    return cast("list[FilaHistorialPendiente]", filas)


def estado_actual(conn: _PgConnAdapter, id_externo: str) -> dict[str, object] | None:
    """:data:`COLUMNAS_ESTADO_ACTUAL` de la licitación, o ``None`` si ya no existe."""
    fila = conn.execute(
        "SELECT " + ", ".join(COLUMNAS_ESTADO_ACTUAL) + " FROM licitaciones WHERE id_externo = %s",
        (id_externo,),
    ).fetchone()
    if fila is None:
        return None
    return dict(zip(COLUMNAS_ESTADO_ACTUAL, fila, strict=False))


def insertar_evento(
    conn: _PgConnAdapter,
    *,
    licitacion_id: str,
    tipo: str,
    fecha: str,
    campo: str,
    valor_antes: str | None,
    valor_despues: str | None,
    importe_delta: float | None,
    detalle: str,
    history_id: int,
) -> None:
    """Escribe un evento; idempotente por ``(history_id, tipo, campo)``.

    Re-procesar la misma fila de historial no duplica: el índice único
    ``idx_eventos_dedupe`` convierte el segundo ``INSERT`` en un no-op.
    """
    conn.execute(
        "INSERT INTO contrato_eventos "
        "(licitacion_id, tipo, fecha, campo, valor_antes, valor_despues, "
        " importe_delta, detalle, history_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (history_id, tipo, COALESCE(campo, '')) "
        "WHERE history_id IS NOT NULL DO NOTHING",
        (
            licitacion_id,
            tipo,
            fecha,
            campo,
            valor_antes,
            valor_despues,
            importe_delta,
            detalle,
            history_id,
        ),
    )


def timeline(licitacion_id: str) -> list[dict[str, Any]]:
    """Línea de tiempo completa de un contrato.

    Une los eventos materializados con los hitos implícitos en los datos:
    publicación (licitaciones.fecha_publicacion) y adjudicaciones por empresa
    (adjudicaciones.fecha_adjudicacion, con nombre canónico del maestro).
    """
    with connect_read() as c:
        return rows_to_dicts(
            c.execute(
                """
                SELECT fecha, tipo, campo, valor_antes, valor_despues,
                       importe_delta, detalle
                FROM contrato_eventos WHERE licitacion_id = %s
                UNION ALL
                SELECT substr(l.fecha_publicacion, 1, 10), 'publicacion',
                       NULL, NULL, NULL, NULL, l.titulo
                FROM licitaciones l
                WHERE l.id_externo = %s AND l.fecha_publicacion IS NOT NULL
                UNION ALL
                SELECT substr(a.fecha_adjudicacion, 1, 10), 'adjudicacion',
                       'adjudicatario', NULL, COALESCE(e.nombre_canonico, a.nombre),
                       a.importe_adjudicado,
                       'adjudicado a ' || COALESCE(e.nombre_canonico, a.nombre)
                FROM adjudicaciones a
                LEFT JOIN empresas e ON e.empresa_id = a.empresa_id
                WHERE a.licitacion_id = %s AND a.fecha_adjudicacion IS NOT NULL
                ORDER BY 1
                """,
                (licitacion_id, licitacion_id, licitacion_id),
            )
        )


def _filtro_eventos(
    *,
    tipos: tuple[str, ...] | None,
    dias: int,
    desde: str | None,
    hasta: str | None,
    filters: LicitacionesFilters | None,
) -> tuple[str, list[Any]]:
    """``WHERE`` del feed sobre ``contrato_eventos ev JOIN licitaciones l``.

    Una sola cláusula para la lista y para el reparto por tipo: si cada uno
    construyera la suya, el recuento podría medir otra ventana u otro ámbito que
    las filas que resume.

    Las fechas van aparte de ``filters`` a propósito: ahí acotarían
    ``fecha_publicacion`` (cuándo se publicó el expediente) y aquí lo que se
    pregunta es cuándo se movió el contrato. ``desde`` sustituye a la ventana
    relativa de ``dias``; ``hasta`` la remata por arriba.
    """
    cutoff_expr = "to_char(CURRENT_DATE - (%s * INTERVAL '1 day'), 'YYYY-MM-DD')"
    clauses: list[str] = []
    params: list[object] = []
    if desde:
        clauses.append("ev.fecha >= %s")
        params.append(desde)
    else:
        # cutoff_expr es un fragmento constante; el valor va con placeholder
        clauses.append(f"ev.fecha >= {cutoff_expr}")
        params.append(max(1, int(dias)))
    if hasta:
        clauses.append("ev.fecha <= %s")
        params.append(hasta)
    if tipos:
        placeholders = ",".join("%s" for _ in tipos)
        clauses.append(f"ev.tipo IN ({placeholders})")
        params.extend(tipos)
    if filters is not None and not filters.is_empty():
        lic_where, lic_params = build_licitaciones_where(filters, alias="l")
        clauses.append(f"({lic_where})")
        params.extend(lic_params)
    return " AND ".join(clauses), params


def eventos_recientes(
    *,
    tipos: tuple[str, ...] | None = None,
    dias: int = 30,
    limit: int = 100,
    desde: str | None = None,
    hasta: str | None = None,
    filters: LicitacionesFilters | None = None,
) -> list[dict[str, Any]]:
    """Feed de eventos recientes (modificaciones, prórrogas…) para el dashboard.

    ``filters`` acota el feed al mismo universo de licitaciones que el resto del
    Resumen (CCAA, tecnología, estado, importe mínimo, búsqueda…): el JOIN con
    ``licitaciones`` ya estaba ahí para el título, así que el ámbito se aplica
    sobre él con el mismo ``WHERE`` que las agregaciones. Ventana y fechas, en
    :func:`_filtro_eventos`.
    """
    where, params = _filtro_eventos(
        tipos=tipos, dias=dias, desde=desde, hasta=hasta, filters=filters
    )
    # Lo único interpolado son fragmentos construidos aquí o en
    # `build_licitaciones_where`; todo valor de usuario va con placeholder.
    sql = (
        "SELECT ev.licitacion_id, ev.tipo, ev.fecha, ev.detalle, ev.importe_delta, "
        "       l.titulo, l.organo_contratacion, l.fuente "
        "FROM contrato_eventos ev "
        "JOIN licitaciones l ON l.id_externo = ev.licitacion_id "
        "WHERE " + where + " ORDER BY ev.fecha DESC LIMIT %s"
    )
    params.append(max(1, min(int(limit), 500)))
    with connect_read() as c:
        return rows_to_dicts(c.execute(sql, params))


def eventos_por_tipo(
    *,
    tipos: tuple[str, ...] | None = None,
    dias: int = 30,
    desde: str | None = None,
    hasta: str | None = None,
    filters: LicitacionesFilters | None = None,
) -> list[dict[str, Any]]:
    """Cuántos movimientos de cada tipo hay en la ventana y el ámbito del feed.

    El feed devuelve como mucho ``limit`` filas, y contarlas en el navegador
    daría el reparto de la muestra, no el de la ventana (ADR-014). Esto cuenta
    en SQL sobre el mismo ``WHERE`` y sin tope: la cardinalidad la acota el
    ``GROUP BY tipo`` (los tipos de eventos derivados y del historial, unos
    pocos), no el número de movimientos (ADR-023).
    """
    where, params = _filtro_eventos(
        tipos=tipos, dias=dias, desde=desde, hasta=hasta, filters=filters
    )
    sql = (
        "SELECT ev.tipo, COUNT(*) AS n "
        "FROM contrato_eventos ev "
        "JOIN licitaciones l ON l.id_externo = ev.licitacion_id "
        "WHERE " + where + " GROUP BY ev.tipo ORDER BY n DESC, ev.tipo"
    )
    with connect_read() as c:
        return [{"tipo": tipo, "n": int(n)} for tipo, n in c.execute(sql, params).fetchall()]


# Los dos únicos tipos que hoy se usan como proxy de satisfacción del cliente
# en el etiquetado de retención. Se acotan en SQL para no traer a Python el
# resto del log de eventos (adjudicacion, formalizacion, anulacion, ...).
TIPOS_SATISFACCION: tuple[str, ...] = ("modificacion", "prorroga")


def contar_por_licitacion_y_tipo(
    tipos: tuple[str, ...] = TIPOS_SATISFACCION,
) -> dict[str, dict[str, int]]:
    """Nº de eventos por licitación y tipo: ``{licitacion_id: {tipo: n}}``.

    Las licitaciones sin eventos de los tipos pedidos **no aparecen** en el
    resultado; el llamador decide qué significa la ausencia (en el etiquetado
    de retención, cero).

    El SQL vivía en ``services/ml/retencion_labels.py``; se movió aquí al sacar
    ese módulo del ratchet TID251.
    """
    # Lo interpolado es solo la lista de `%s` (una por tipo pedido); los valores
    # viajan como parámetros, nunca dentro del SQL.
    placeholders = ",".join("%s" for _ in tipos)
    sql = (
        "SELECT licitacion_id, tipo, COUNT(*) AS n FROM contrato_eventos "
        f"WHERE tipo IN ({placeholders}) GROUP BY licitacion_id, tipo"
    )
    with connect_read() as c:
        rows = rows_to_dicts(c.execute(sql, tipos))
    out: dict[str, dict[str, int]] = defaultdict(dict)
    for r in rows:
        out[str(r["licitacion_id"])][str(r["tipo"])] = int(r["n"])
    return out


def eventos_de_licitacion(licitacion_id: str) -> list[dict[str, Any]]:
    """Los eventos materializados de un contrato, del más antiguo al más nuevo.

    Es lo que enseña ``GET /pursuits/cartera/{id}/eventos``: el ciclo de vida
    del contrato vigente (adjudicación, formalización, modificaciones,
    prórrogas, anulación) tal como lo derivó ``services/contract_events.py``.
    Sólo la tabla, sin los hitos implícitos que añade :func:`timeline`
    (publicación, adjudicaciones): la
    cartera pregunta qué le pasó al contrato **después** de ganarlo.

    ``id`` desempata dos eventos del mismo día en el orden en que se
    derivaron, que es el orden del historial.
    """
    with connect_read() as c:
        return rows_to_dicts(
            c.execute(
                "SELECT id, licitacion_id, tipo, fecha, campo, valor_antes, valor_despues, "
                "       importe_delta, detalle "
                "FROM contrato_eventos WHERE licitacion_id = %s ORDER BY fecha, id",
                (licitacion_id,),
            )
        )
