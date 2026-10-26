"""Cifras de verificación de la reingesta única de PLACSP (solo lectura).

La reingesta de los ZIP mensuales que trae la fase B de identidad
(``docs/rfc/2026-10-24-rfc-identidad-placsp-organo-expediente.md``) corrige a la
vez otros cuatro defectos del dato histórico
(``docs/runbooks/reingesta-unica-placsp.md``). Este módulo cuenta lo que cada
uno deja ver en la base, para medir antes y después:

1. **Base del importe** (ADR-032): filas PLACSP con ``importe_tipo`` desconocido
   o nulo. Puerta del plan 2026-10 (V2): por debajo del 10 %.
2. **Umbral de la solvencia económica** (P2 «condiciones oficiales de CODICE»):
   requisitos económicos con ``umbral_importe`` no nulo. Hasta el 2026-10-24 el
   parser no lo leía (0 de 4.069).
3. **Arreglos del parser del 2026-10-25**: ``provincia = 'España'`` (NUTS de
   país), ceros en los importes de ``adjudicaciones`` y en ``licitacion_garantias``,
   y ``fecha_publicacion`` con hora.

Las colisiones de expediente entre órganos las cuenta
``db.repositories.identidad``; el script las junta con estas.

``desde`` (ISO) restringe a las filas cuya ``fecha_extraccion`` es posterior: es
cómo se separa «lo que la reingesta tocó» de «lo que no le llegó» (filas que el
filtro TI ya no admite, o fuera de los meses reingeridos).

Todo el SQL vive aquí (ADR-022). Solo ``connect_read``.
"""

from __future__ import annotations

from typing import TypedDict

from db.database import connect_read
from db.repositories.base import rows_to_dicts, typed_rows

__all__ = [
    "CerosHijas",
    "LicitacionesPlacsp",
    "SolvenciaEconomica",
    "ceros_en_hijas",
    "licitaciones_placsp",
    "solvencia_economica",
]

#: Filas del feed principal de PLACSP en sus dos carriles. ``%%`` porque estas
#: consultas llevan parámetros y psycopg interpreta ``%``.
_ES_PLACSP = "(l.fuente = 'placsp' OR l.fuente LIKE 'bulk\\_%%')"

#: Filtro opcional por ``fecha_extraccion``: dos veces el mismo parámetro.
_DESDE = "(%s::text IS NULL OR l.fecha_extraccion >= %s::text)"


class LicitacionesPlacsp(TypedDict):
    """Columnas de :func:`licitaciones_placsp`."""

    filas: int
    importe_tipo_desconocido: int
    importe_sin_iva: int
    importe_con_iva: int
    con_base_sin_iva: int
    provincia_espana: int
    fecha_publicacion_con_hora: int


class SolvenciaEconomica(TypedDict):
    """Columnas de :func:`solvencia_economica`."""

    requisitos: int
    con_umbral: int
    licitaciones: int
    licitaciones_con_umbral: int


class CerosHijas(TypedDict):
    """Columnas de :func:`ceros_en_hijas`, una fila por grupo de fuente."""

    grupo: str
    adjudicaciones: int
    adjudicaciones_con_cero: int
    garantias: int
    garantias_con_cero: int


_SQL_LICITACIONES = f"""
SELECT count(*) AS filas,
       count(*) FILTER (WHERE l.importe_tipo IS NULL OR l.importe_tipo = 'desconocido')
         AS importe_tipo_desconocido,
       count(*) FILTER (WHERE l.importe_tipo = 'sin_iva') AS importe_sin_iva,
       count(*) FILTER (WHERE l.importe_tipo = 'con_iva') AS importe_con_iva,
       count(*) FILTER (WHERE l.importe_base_sin_iva IS NOT NULL) AS con_base_sin_iva,
       count(*) FILTER (WHERE l.provincia = 'España') AS provincia_espana,
       count(*) FILTER (WHERE length(l.fecha_publicacion) > 10) AS fecha_publicacion_con_hora
FROM licitaciones l
WHERE {_ES_PLACSP} AND {_DESDE}
"""

_SQL_SOLVENCIA = f"""
SELECT count(*) AS requisitos,
       count(s.umbral_importe) AS con_umbral,
       count(DISTINCT s.licitacion_id) AS licitaciones,
       count(DISTINCT s.licitacion_id) FILTER (WHERE s.umbral_importe IS NOT NULL)
         AS licitaciones_con_umbral
FROM licitacion_solvencia s
JOIN licitaciones l ON l.id_externo = s.licitacion_id
WHERE s.clase = 'economica' AND {_ES_PLACSP} AND {_DESDE}
"""

# Un 0 en estos importes es «no informado» desde el 2026-10-25
# (`scraper.codice_parser._importe_informado`); presupuesto y valor estimado
# no se tocaron y no se cuentan. El conector de empresas vigiladas escribe sus
# propias filas (`placsp_watched_company_awards`) y la reingesta del feed no
# las alcanza: va en su propio grupo para que no se confunda con un fallo.
_GRUPO = (
    "CASE WHEN l.fuente = 'placsp_watched_company_awards' THEN 'placsp_watched_company_awards' "
    "ELSE 'placsp' END"
)
_ES_PLACSP_O_VIGILADAS = f"({_ES_PLACSP} OR l.fuente = 'placsp_watched_company_awards')"

_SQL_CEROS = f"""
WITH adj AS (
  SELECT {_GRUPO} AS grupo,
         count(*) AS total,
         count(*) FILTER (WHERE a.importe_adjudicado = 0 OR a.importe_pagable = 0
                            OR a.oferta_minima = 0 OR a.oferta_maxima = 0) AS con_cero
  FROM adjudicaciones a
  JOIN licitaciones l ON l.id_externo = a.licitacion_id
  WHERE {_ES_PLACSP_O_VIGILADAS} AND {_DESDE}
  GROUP BY 1
), gar AS (
  SELECT {_GRUPO} AS grupo,
         count(*) AS total,
         count(*) FILTER (WHERE g.porcentaje = 0 OR g.importe = 0) AS con_cero
  FROM licitacion_garantias g
  JOIN licitaciones l ON l.id_externo = g.licitacion_id
  WHERE {_ES_PLACSP_O_VIGILADAS} AND {_DESDE}
  GROUP BY 1
)
SELECT COALESCE(adj.grupo, gar.grupo) AS grupo,
       COALESCE(adj.total, 0) AS adjudicaciones,
       COALESCE(adj.con_cero, 0) AS adjudicaciones_con_cero,
       COALESCE(gar.total, 0) AS garantias,
       COALESCE(gar.con_cero, 0) AS garantias_con_cero
FROM adj FULL OUTER JOIN gar ON gar.grupo = adj.grupo
ORDER BY 1
"""


def licitaciones_placsp(*, desde: str | None = None) -> LicitacionesPlacsp:
    """Base del importe, provincia «España» y fechas con hora en filas PLACSP."""
    with connect_read() as c:
        filas = typed_rows(
            LicitacionesPlacsp, rows_to_dicts(c.execute(_SQL_LICITACIONES, (desde, desde)))
        )
    return filas[0]


def solvencia_economica(*, desde: str | None = None) -> SolvenciaEconomica:
    """Requisitos de solvencia económica de PLACSP y cuántos traen umbral."""
    with connect_read() as c:
        filas = typed_rows(
            SolvenciaEconomica, rows_to_dicts(c.execute(_SQL_SOLVENCIA, (desde, desde)))
        )
    return filas[0]


def ceros_en_hijas(*, desde: str | None = None) -> list[CerosHijas]:
    """Importes a 0 en adjudicaciones y garantías, por grupo de fuente PLACSP."""
    with connect_read() as c:
        return typed_rows(
            CerosHijas, rows_to_dicts(c.execute(_SQL_CEROS, (desde, desde, desde, desde)))
        )
