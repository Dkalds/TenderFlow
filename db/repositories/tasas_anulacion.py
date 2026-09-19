"""Tasa de anulación o desierto por órgano (F1.4), precalculada.

La escribe ``scheduler/aggregates_precompute.py`` una vez por pasada y la lee
``services/analytics/scoring.py`` por clave. El esquema lo crea ``v141``.

Qué cuenta como «fallido»
-------------------------
- ``licitaciones.estado = 'ANUL'``: la normalización de ``v91`` ya pliega ahí
  las anulaciones y los desistimientos.
- Un resultado de adjudicación que la Plataforma publica como desierto,
  desistimiento o renuncia (``adjudicaciones.result_code`` de la lista
  ``TenderResultCode`` de CODICE: ``3`` desierto, ``4`` desistimiento, ``5``
  renuncia, ``6`` y ``7`` desierto provisional y definitivo). El desierto no
  tiene código de estado propio en PLACSP y solo llega por ahí.

El denominador son los expedientes **resueltos** de la ventana —adjudicados,
formalizados o fallidos—: uno todavía en plazo no ha tenido ocasión de
anularse, y contarlo diluiría la tasa de los órganos con mucho volumen abierto.

Módulo de funciones y no clase: el mismo estrato que ``db/repositories/*``
(AGENTS.md §3.10), y dos consultas sin estado compartido no piden más.
"""

from __future__ import annotations

from typing import Any

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts
from db.sql_fragments import iso_guard

__all__ = [
    "CODIGOS_RESULTADO_FALLIDO",
    "TODAS",
    "clave_organo",
    "recalcular",
    "tasas_por_organos",
]

#: `cpv4` de la fila que agrega todo el órgano.
TODAS = "*"

#: `TenderResultCode` que no terminan en contrato. Ver la cabecera.
CODIGOS_RESULTADO_FALLIDO: tuple[str, ...] = ("3", "4", "5", "6", "7")

#: Techo de filas de una lectura para el scoring.
MAX_FILAS_POR_CONSULTA = 20_000


def clave_organo(nombre: Any) -> str | None:
    """La clave con la que se guarda un órgano: nombre plegado, o ``None``.

    Tiene que coincidir con el ``lower(btrim(...))`` de :func:`recalcular`,
    que es lo que hace Postgres; ``str.lower`` y ``lower`` de Postgres pliegan
    igual las letras del castellano.
    """
    if nombre is None:
        return None
    texto = str(nombre).strip().lower()
    return texto or None


def recalcular(*, desde_iso: str) -> int:
    """Reemplaza la tabla con las tasas de la ventana ``[desde_iso, hoy]``.

    Todo en SQL y en una transacción: un lector concurrente ve las tasas de la
    pasada anterior o las de esta, nunca una tabla a medias. Devuelve cuántas
    filas quedaron.
    """
    marcas = ", ".join(["%s"] * len(CODIGOS_RESULTADO_FALLIDO))
    guard = iso_guard("l.fecha_publicacion")
    sql = (
        "WITH base AS ("
        "  SELECT lower(btrim(l.organo_contratacion)) AS organo_key, "
        "         CASE WHEN l.cpv ~ '^[0-9]{4}' THEN substr(l.cpv, 1, 4) END AS cpv4, "
        "         (COALESCE(l.estado, '') = 'ANUL' OR EXISTS ("
        "            SELECT 1 FROM adjudicaciones a "
        f"            WHERE a.licitacion_id = l.id_externo AND a.result_code IN ({marcas})"
        "         )) AS fallida, "
        "         l.estado "
        "  FROM licitaciones l "
        "  WHERE l.organo_contratacion IS NOT NULL "
        "    AND btrim(l.organo_contratacion) <> '' "
        f"    AND {guard} AND l.fecha_publicacion >= %s"
        "), resueltos AS ("
        "  SELECT organo_key, cpv4, fallida FROM base "
        "  WHERE fallida OR estado IN ('ADJ', 'RES')"
        ") "
        "INSERT INTO tasas_anulacion_organo "
        "(organo_key, cpv4, n_expedientes, n_fallidos, tasa, desde, updated_at) "
        "SELECT organo_key, "
        f"       CASE WHEN GROUPING(cpv4) = 1 THEN '{TODAS}' ELSE cpv4 END, "
        "       COUNT(*), COUNT(*) FILTER (WHERE fallida), "
        "       (COUNT(*) FILTER (WHERE fallida))::double precision / COUNT(*), "
        "       %s, %s "
        "FROM resueltos "
        "GROUP BY GROUPING SETS ((organo_key), (organo_key, cpv4)) "
        "HAVING GROUPING(cpv4) = 1 OR cpv4 IS NOT NULL"
    )
    ahora = now_utc_iso()
    with connect() as conn:
        conn.execute("DELETE FROM tasas_anulacion_organo")
        conn.execute(sql, (*CODIGOS_RESULTADO_FALLIDO, desde_iso, desde_iso, ahora))
        fila = conn.execute("SELECT COUNT(*) FROM tasas_anulacion_organo").fetchone()
    return int(fila[0]) if fila else 0


def tasas_por_organos(organos: list[str]) -> dict[tuple[str, str], tuple[int, int]]:
    """``{(organo_key, cpv4): (n_expedientes, n_fallidos)}`` de esos órganos.

    ``organos`` ya viene plegado con :func:`clave_organo`. Trae el total del
    órgano y todos sus CPV-4: son pocas filas por órgano, y así el scoring
    elige por fila sin una consulta más.
    """
    claves = sorted({o for o in organos if o})
    if not claves:
        return {}
    marcas = ", ".join(["%s"] * len(claves))
    with connect_read() as conn:
        filas = rows_to_dicts(
            conn.execute(
                "SELECT organo_key, cpv4, n_expedientes, n_fallidos "
                f"FROM tasas_anulacion_organo WHERE organo_key IN ({marcas}) "
                # Cota (ADR-023): un lote del Radar son cientos de órganos con
                # unas decenas de CPV-4 cada uno; el techo solo evita que un
                # lote patológico materialice la tabla entera.
                "LIMIT %s",
                [*claves, MAX_FILAS_POR_CONSULTA],
            )
        )
    return {
        (str(f["organo_key"]), str(f["cpv4"])): (int(f["n_expedientes"]), int(f["n_fallidos"]))
        for f in filas
    }
