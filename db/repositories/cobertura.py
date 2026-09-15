"""Medición de cobertura y solape entre fuentes, por comunidad autónoma.

Existe para responder **con un número** a la pregunta que D16 dejó abierta el
2026-09-06: los portales de Madrid, Andalucía y la Comunidad Valenciana están
declarados fuera de alcance «hasta petición escrita de un cliente», pero nadie
sabe cuánto de la contratación TI de esas comunidades llega ya a PLACSP por
agregación (``estado = 'AGR'``, los avisos agregados) o por publicación
directa. Sin esa cifra la decisión de abrir un conector se toma a ciegas en
las dos direcciones: escribir tres conectores para datos que ya tenemos, o
seguir sin ellos creyendo que la agregación cubre lo que no cubre.

Todo el SQL vive aquí (ADR-022); ``scripts/medir_solape_agregados.py`` solo
formatea. Las cuatro consultas usan el mismo corte de fecha sobre
``fecha_pub_d`` (columna ``date`` generada, v68) y el mismo predicado de
universo tecnológico que la superficie pública y la analítica
(``db.sql_fragments.universo_tecnologico_sql``): comparar cifras con
denominadores distintos es exactamente lo que este módulo evita.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from db.database import connect_read
from db.repositories.base import rows_to_dicts
from db.sql_fragments import universo_tecnologico_sql

#: Estado con el que PLACSP marca los avisos que agrega de otras plataformas.
ESTADO_AGREGADO = "AGR"


@dataclass(frozen=True)
class SolapePorCcaa:
    """Una fila del informe: cuántos expedientes tiene una CCAA y por dónde entran."""

    ccaa: str
    total: int
    universo_ti: int
    universo_ti_agregados: int
    universo_ti_por_fuente: dict[str, int]

    @property
    def pct_agregados(self) -> float | None:
        """Porcentaje del universo TI que llegó como aviso agregado."""
        if self.universo_ti == 0:
            return None
        return round(100.0 * self.universo_ti_agregados / self.universo_ti, 1)


@dataclass(frozen=True)
class OrganoPorFuente:
    organo: str
    expedientes: int
    fuentes: dict[str, int]


def _sql_ccaa(desde: date) -> tuple[str, tuple[Any, ...]]:
    universo = universo_tecnologico_sql("l")
    sql = (
        "SELECT COALESCE(l.ccaa, '(sin CCAA)') AS ccaa, "
        "       COUNT(*) AS total, "
        f"       COUNT(*) FILTER (WHERE {universo}) AS universo_ti, "
        f"       COUNT(*) FILTER (WHERE ({universo}) AND l.estado = %s) AS universo_ti_agregados "
        "FROM licitaciones l "
        "WHERE l.fecha_pub_d >= %s "
        "GROUP BY 1 ORDER BY 3 DESC, 1"
    )
    return sql, (ESTADO_AGREGADO, desde)


def _sql_ccaa_fuente(desde: date) -> tuple[str, tuple[Any, ...]]:
    universo = universo_tecnologico_sql("l")
    sql = (
        "SELECT COALESCE(l.ccaa, '(sin CCAA)') AS ccaa, l.fuente, COUNT(*) AS n "
        "FROM licitaciones l "
        f"WHERE l.fecha_pub_d >= %s AND ({universo}) "
        "GROUP BY 1, 2"
    )
    return sql, (desde,)


def solape_por_ccaa(*, desde: date) -> list[SolapePorCcaa]:
    """Expedientes por CCAA desde ``desde``: total, universo TI, agregados y fuente.

    ``fuente`` es la etiqueta del conector que trajo la fila (``placsp``,
    ``pscp``, ``galicia_rss``, ``bulk_YYYYMM``...). Un expediente de Madrid
    con ``fuente = placsp`` y ``estado = AGR`` es la prueba de que el portal
    madrileño ya llega por agregación; uno con ``fuente = placsp`` y otro
    estado es publicación directa en la Plataforma.
    """
    sql_a, params_a = _sql_ccaa(desde)
    sql_b, params_b = _sql_ccaa_fuente(desde)
    with connect_read() as c:
        filas = rows_to_dicts(c.execute(sql_a, params_a))
        por_fuente = rows_to_dicts(c.execute(sql_b, params_b))
    fuentes: dict[str, dict[str, int]] = {}
    for fila in por_fuente:
        fuentes.setdefault(str(fila["ccaa"]), {})[str(fila["fuente"])] = int(fila["n"])
    return [
        SolapePorCcaa(
            ccaa=str(f["ccaa"]),
            total=int(f["total"]),
            universo_ti=int(f["universo_ti"]),
            universo_ti_agregados=int(f["universo_ti_agregados"]),
            universo_ti_por_fuente=dict(sorted(fuentes.get(str(f["ccaa"]), {}).items())),
        )
        for f in filas
    ]


def organos_por_fuente(*, ccaa: str, desde: date, limit: int = 15) -> list[OrganoPorFuente]:
    """Los órganos con más expedientes TI de una CCAA y por qué fuente llegan.

    Agrupa por ``organo_id`` cuando el maestro (ADR-032) lo ha resuelto y por
    el texto en caso contrario, con la misma lectura dual que la analítica;
    el nombre que se muestra es el canónico si existe.
    """
    universo = universo_tecnologico_sql("l")
    sql = (
        "WITH base AS ("
        "  SELECT COALESCE(o.nombre_canonico, l.organo_contratacion, '(sin órgano)') AS organo, "
        "         COALESCE(l.organo_id::text, lower(l.organo_contratacion), '') AS clave, "
        "         l.fuente "
        "  FROM licitaciones l LEFT JOIN organos o ON o.organo_id = l.organo_id "
        f"  WHERE l.fecha_pub_d >= %s AND l.ccaa = %s AND ({universo})"
        ") "
        "SELECT clave, MIN(organo) AS organo, fuente, COUNT(*) AS n "
        "FROM base GROUP BY clave, fuente"
    )
    with connect_read() as c:
        filas = rows_to_dicts(c.execute(sql, (desde, ccaa)))
    acumulado: dict[str, dict[str, Any]] = {}
    for fila in filas:
        entrada = acumulado.setdefault(
            str(fila["clave"]), {"organo": str(fila["organo"]), "fuentes": {}, "n": 0}
        )
        entrada["fuentes"][str(fila["fuente"])] = int(fila["n"])
        entrada["n"] += int(fila["n"])
    ordenado = sorted(acumulado.values(), key=lambda e: (-int(e["n"]), str(e["organo"])))
    return [
        OrganoPorFuente(
            organo=str(e["organo"]),
            expedientes=int(e["n"]),
            fuentes=dict(sorted(e["fuentes"].items())),
        )
        for e in ordenado[:limit]
    ]
