"""Escritura por lotes de ``resoluciones_recurso`` (TACRC).

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

from collections.abc import Mapping, Sequence
from typing import Any

from db.database import connect, now_utc_iso

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
