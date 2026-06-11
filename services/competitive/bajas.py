"""Análisis de bajas: presupuesto de licitación vs importe adjudicado.

Responde "¿cuánto hay que bajar para ganar?" segmentado por empresa, órgano
de contratación o CPV. Solo considera pares con presupuesto y adjudicación
positivos y descarta outliers donde el adjudicado supera el presupuesto en
más de un 50% (errores de fuente o modificados mal atribuidos).
"""

from __future__ import annotations

from typing import Any

from db.database import connect_read
from db.repositories.base import rows_to_dicts
from services.dedupe import exclude_duplicados_sql

_GROUP_COLUMNS = {
    "empresa": ("a.empresa_id", "COALESCE(e.nombre_canonico, a.nombre)"),
    "organo": (None, "l.organo_contratacion"),
    "cpv": (None, "substr(l.cpv, 1, 2)"),
    "ccaa": (None, "l.ccaa"),
}

# Condiciones de validez de un par presupuesto/adjudicado
_VALID_PAIR = (
    "l.importe > 0 AND a.importe_adjudicado > 0 AND a.importe_adjudicado <= l.importe * 1.5"
)


def bajas_agregadas(
    *,
    group_by: str = "empresa",
    min_contratos: int = 3,
    cpv_prefix: str | None = None,
    ccaa: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Baja media/mediana-aproximada por dimensión.

    ``baja_pct`` = (presupuesto - adjudicado) / presupuesto * 100. Devuelve
    media, mínimo, máximo, nº de contratos e importe total por grupo;
    ``min_contratos`` filtra grupos sin masa estadística.
    """
    if group_by not in _GROUP_COLUMNS:
        raise ValueError(f"group_by inválido: {group_by!r} (válidos: {sorted(_GROUP_COLUMNS)})")
    id_col, label_col = _GROUP_COLUMNS[group_by]

    select_id = f"{id_col} AS grupo_id," if id_col else ""
    group_cols = f"{id_col}, {label_col}" if id_col else label_col

    # S608: las columnas interpoladas salen de _GROUP_COLUMNS (whitelist
    # interna) y _VALID_PAIR es un fragmento constante; los valores van con ?.
    sql = f"""
        SELECT {select_id}
               {label_col} AS grupo,
               COUNT(*) AS contratos,
               ROUND(AVG((l.importe - a.importe_adjudicado) / l.importe * 100), 2) AS baja_media_pct,
               ROUND(MIN((l.importe - a.importe_adjudicado) / l.importe * 100), 2) AS baja_min_pct,
               ROUND(MAX((l.importe - a.importe_adjudicado) / l.importe * 100), 2) AS baja_max_pct,
               COALESCE(SUM(a.importe_adjudicado), 0) AS importe_total,
               ROUND(AVG(a.n_ofertas_recibidas), 1) AS ofertas_medias
        FROM adjudicaciones a
        JOIN licitaciones l ON l.id_externo = a.licitacion_id
        LEFT JOIN empresas e ON e.empresa_id = a.empresa_id
        WHERE {_VALID_PAIR} AND {exclude_duplicados_sql()}
    """  # noqa: S608
    params: list[Any] = []
    if cpv_prefix:
        sql += " AND l.cpv LIKE ?"
        params.append(f"{cpv_prefix}%")
    if ccaa:
        sql += " AND l.ccaa = ?"
        params.append(ccaa)
    sql += f"""
        GROUP BY {group_cols}
        HAVING COUNT(*) >= ? AND grupo IS NOT NULL
        ORDER BY contratos DESC
        LIMIT ?
    """
    params.extend([max(1, int(min_contratos)), max(1, min(int(limit), 500))])

    with connect_read() as c:
        return rows_to_dicts(c.execute(sql, params))


def baja_de_referencia(
    *, organo: str | None = None, cpv_prefix: str | None = None
) -> dict[str, Any]:
    """Baja media y rango en un segmento concreto (órgano y/o CPV).

    Es el dato accionable al preparar una oferta: "en este órgano, para este
    CPV, la baja ganadora media es X%". Devuelve también la distribución de
    ofertas recibidas como indicador de presión competitiva.
    """
    sql = f"""
        SELECT COUNT(*) AS contratos,
               ROUND(AVG((l.importe - a.importe_adjudicado) / l.importe * 100), 2) AS baja_media_pct,
               ROUND(MIN((l.importe - a.importe_adjudicado) / l.importe * 100), 2) AS baja_min_pct,
               ROUND(MAX((l.importe - a.importe_adjudicado) / l.importe * 100), 2) AS baja_max_pct,
               ROUND(AVG(a.n_ofertas_recibidas), 1) AS ofertas_medias
        FROM adjudicaciones a
        JOIN licitaciones l ON l.id_externo = a.licitacion_id
        WHERE {_VALID_PAIR} AND {exclude_duplicados_sql()}
    """  # noqa: S608 — _VALID_PAIR es un fragmento constante; valores con ?
    params: list[Any] = []
    if organo:
        sql += " AND l.organo_contratacion = ?"
        params.append(organo)
    if cpv_prefix:
        sql += " AND l.cpv LIKE ?"
        params.append(f"{cpv_prefix}%")

    with connect_read() as c:
        rows = rows_to_dicts(c.execute(sql, params))
    result = rows[0] if rows else {}
    result["organo"] = organo
    result["cpv_prefix"] = cpv_prefix
    return result
