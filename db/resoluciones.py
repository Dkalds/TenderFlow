"""Escritura por lotes de ``resoluciones_recurso`` (TACRC).

También la vinculación a licitaciones (:func:`vincular_pendientes`) y el
listado (:func:`listar_resoluciones`), desde el 2026-10-25.

Baja aquí desde ``services/resoluciones.py`` (ADR-022) al pasar a lotes. Antes
era un ``SELECT`` y un ``INSERT``/``UPDATE`` **por resolución**, cada uno en su
viaje: con el índice del Pleno (17 resoluciones) daba igual, pero el índice
completo trae del orden de dos mil por año (1.891 en 2025 según la memoria del
tribunal), y desde los runners de Actions —en EE. UU., con la base en París—
cada viaje cuesta 95-150 ms: un año entero serían ocho minutos de red, más que
el step de 10 en cuanto hubiera dos. Es el mismo diagnóstico que la resolución
de empresas de PSCP (backlog P1, 2026-10-03), y el mismo arreglo: un viaje para
saber cuáles existen y un ``executemany`` con ``ON CONFLICT``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts

#: Columnas que escribe el lote, en el orden de los marcadores.
_COLUMNAS: tuple[str, ...] = (
    "tribunal",
    "numero_resolucion",
    "numero_recurso",
    "fecha",
    "expediente",
    "organo",
    "sentido",
    "url_pdf",
    "resumen",
    "licitacion_id",
)

# El UPDATE del conflicto no pisa `licitacion_id` ya asignado por la
# vinculación (`services.resoluciones.link_unlinked`): la resolución se
# re-ingiere en cada pasada sin vínculo y lo perdería.
_UPSERT = (
    f"INSERT INTO resoluciones_recurso ({', '.join(_COLUMNAS)}, fecha_extraccion) "
    f"VALUES ({', '.join(['%s'] * (len(_COLUMNAS) + 1))}) "
    "ON CONFLICT (tribunal, numero_resolucion) DO UPDATE SET "
    "numero_recurso = excluded.numero_recurso, fecha = excluded.fecha, "
    "expediente = excluded.expediente, organo = excluded.organo, "
    "sentido = excluded.sentido, url_pdf = excluded.url_pdf, resumen = excluded.resumen, "
    "licitacion_id = COALESCE(resoluciones_recurso.licitacion_id, excluded.licitacion_id), "
    "fecha_extraccion = excluded.fecha_extraccion"
)


def upsert_resoluciones_lote(filas: Sequence[Mapping[str, Any]]) -> tuple[int, int]:
    """Inserta o actualiza un lote de resoluciones. Devuelve ``(nuevas, actualizadas)``.

    Idempotente (invariante §3.2): re-ejecutar el mismo lote no duplica, porque
    la clave natural ``(tribunal, numero_resolucion)`` es ``UNIQUE``. Cuenta
    como nueva cada clave que no existía antes del lote; el resto de filas
    —incluida una clave repetida dentro del mismo lote— como actualizadas, que
    es lo que contaba la versión fila a fila.
    """
    if not filas:
        return 0, 0
    tribunales = [str(f["tribunal"]) for f in filas]
    numeros = [str(f["numero_resolucion"]) for f in filas]
    ahora = now_utc_iso()
    with connect() as c:
        existentes = {
            (str(t), str(n))
            for t, n in c.execute(
                "SELECT tribunal, numero_resolucion FROM resoluciones_recurso "
                "WHERE (tribunal, numero_resolucion) IN "
                "(SELECT * FROM unnest(%s::text[], %s::text[]))",
                (tribunales, numeros),
            ).fetchall()
        }
        c.executemany(
            _UPSERT,
            [[fila.get(col) for col in _COLUMNAS] + [ahora] for fila in filas],
        )
    nuevas = len(set(zip(tribunales, numeros, strict=True)) - existentes)
    return nuevas, len(filas) - nuevas


def resoluciones_vinculadas_sin_documento(
    prefijo_hash: str, *, limit: int = 500
) -> list[dict[str, str]]:
    """Resoluciones vinculadas a una licitación cuyo PDF aún no es documento suyo.

    Es la cola de :func:`scraper.connectors.tacrc.registrar_documentos`: el PDF
    de una resolución vinculada entra en ``documentos`` como adjunto de la
    licitación, y el ``NOT EXISTS`` hace que cada pasada solo mire las que
    faltan. La identidad del documento es ``prefijo_hash`` + el número de
    resolución con ``/`` cambiada por ``-`` (``tacrc-1758-2025``); el conector
    construye la misma cadena en Python, y si las dos divergieran cada pasada
    volvería a proponer las mismas resoluciones —sin duplicar nada, porque
    ``upsert_meta`` es idempotente, pero gastando viajes—.
    """
    with connect() as c:
        filas = c.execute(
            "SELECT r.licitacion_id, r.numero_resolucion, r.url_pdf "
            "FROM resoluciones_recurso r "
            "WHERE r.licitacion_id IS NOT NULL AND r.url_pdf IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM documentos d "
            "  WHERE d.licitacion_id = r.licitacion_id "
            "  AND d.source_hash = %s || translate(r.numero_resolucion, '/', '-')) "
            "ORDER BY r.fecha DESC NULLS LAST, r.numero_resolucion "
            "LIMIT %s",
            (prefijo_hash, max(1, min(int(limit), 5000))),
        ).fetchall()
    return [
        {"licitacion_id": str(lic), "numero_resolucion": str(num), "url_pdf": str(url)}
        for lic, num, url in filas
    ]


#: Emparejador de la vinculación: recibe las resoluciones pendientes y el
#: censo ``(id_externo, organo_contratacion)`` de licitaciones, y devuelve los
#: pares ``(resolución, licitacion_id)`` que se deben escribir. El criterio
#: (expediente natural + órgano normalizado) es de dominio y vive en
#: ``services/resoluciones.py``; aquí solo se lee y se escribe.
Emparejador = Callable[
    [Sequence[dict[str, Any]], Sequence[dict[str, Any]]],
    Iterable[tuple[dict[str, Any], str]],
]


def _registrar_evento_recurso(c: Any, licitacion_id: str, res: Mapping[str, Any]) -> bool:
    """Evento ``recurso`` en la línea de tiempo (solo resoluciones estimatorias)."""
    detalle = f"Resolución {res['tribunal'].upper()} {res['numero_resolucion']} ({res['sentido']})"
    ya_existe = c.execute(
        "SELECT 1 FROM contrato_eventos "
        "WHERE licitacion_id = %s AND tipo = 'recurso' AND detalle = %s",
        (licitacion_id, detalle),
    ).fetchone()
    if ya_existe:
        return False
    c.execute(
        "INSERT INTO contrato_eventos (licitacion_id, tipo, fecha, campo, detalle) "
        "VALUES (%s, 'recurso', %s, 'resolucion', %s)",
        (licitacion_id, str(res.get("fecha") or now_utc_iso())[:10], detalle),
    )
    return True


def vincular_pendientes(emparejar: Emparejador) -> dict[str, int]:
    """Vincula las resoluciones sin ``licitacion_id`` en una sola transacción.

    Lee las pendientes (con expediente) y el censo de licitaciones, pregunta a
    ``emparejar`` qué pares escribir, y por cada uno fija el vínculo y, si la
    resolución es estimatoria, deja el evento ``recurso`` (sin duplicarlo).
    Devuelve ``{"vinculadas", "eventos"}``.
    """
    stats = {"vinculadas": 0, "eventos": 0}
    with connect() as c:
        pendientes = rows_to_dicts(
            c.execute(
                "SELECT id, tribunal, numero_resolucion, fecha, expediente, organo, sentido "
                "FROM resoluciones_recurso "
                "WHERE licitacion_id IS NULL AND expediente IS NOT NULL"
            )
        )
        if not pendientes:
            return stats
        licitaciones = rows_to_dicts(
            c.execute("SELECT id_externo, organo_contratacion FROM licitaciones")
        )
        for res, licitacion_id in emparejar(pendientes, licitaciones):
            c.execute(
                "UPDATE resoluciones_recurso SET licitacion_id = %s WHERE id = %s",
                (licitacion_id, res["id"]),
            )
            stats["vinculadas"] += 1
            if res.get("sentido") == "estimado" and _registrar_evento_recurso(
                c, licitacion_id, res
            ):
                stats["eventos"] += 1
    return stats


def listar_resoluciones(
    *,
    organo: str | None = None,
    sentido: str | None = None,
    desde: str | None = None,
    licitacion_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Listado filtrable de resoluciones (feed de jurisprudencia + detail panel)."""
    sql = (
        "SELECT r.id, r.tribunal, r.numero_resolucion, r.numero_recurso, r.fecha, "
        "       r.expediente, r.organo, r.sentido, r.url_pdf, r.resumen, "
        "       r.licitacion_id, l.titulo AS licitacion_titulo "
        "FROM resoluciones_recurso r "
        "LEFT JOIN licitaciones l ON l.id_externo = r.licitacion_id "
        "WHERE 1=1"
    )
    params: list[object] = []
    if organo:
        sql += " AND r.organo LIKE %s"
        params.append(f"%{organo}%")
    if sentido:
        sql += " AND r.sentido = %s"
        params.append(sentido)
    if desde:
        sql += " AND r.fecha >= %s"
        params.append(desde)
    if licitacion_id:
        sql += " AND r.licitacion_id = %s"
        params.append(licitacion_id)
    sql += " ORDER BY r.fecha DESC, r.numero_resolucion DESC LIMIT %s"
    params.append(max(1, min(int(limit), 500)))
    with connect_read() as c:
        return rows_to_dicts(c.execute(sql, params))
