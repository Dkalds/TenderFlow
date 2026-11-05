"""SQL del análisis de bajas: presupuesto de licitación frente a adjudicado.

La regla de qué base se compara (``filtro_base``) la decide
``services.competitive.bajas``; aquí solo se arma y ejecuta la consulta
(ADR-022). El presupuesto de referencia es el del lote cuando la adjudicación
tiene uno (``BAJA_PCT_SQL``) y ``VALID_PAIR_LOTE`` descarta los pares sin
presupuesto o con un adjudicado que lo supera en más de un 50 %.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from db.database import connect_read
from db.repositories.base import rows_to_dicts
from db.sql_fragments import (
    BAJA_PCT_SQL,
    TECHNOLOGY_OBSERVED_SQL,
    VALID_PAIR_LOTE,
    exclude_duplicados_sql,
    round_sql,
)

_GROUP_COLUMNS = {
    "empresa": ("a.empresa_id", "COALESCE(e.nombre_canonico, a.nombre)"),
    "organo": (None, "l.organo_contratacion"),
    "cpv": (None, "substr(l.cpv, 1, 2)"),
    "ccaa": (None, "l.ccaa"),
}


def filas_bajas_agregadas(
    *,
    group_by: str,
    filtro_base: str,
    min_contratos: int,
    cpv_prefix: str | None,
    ccaa: str | None,
    limit: int,
    fecha_desde: date | None,
    fecha_hasta: date | None,
    importe_min: float | None,
) -> list[dict[str, Any]]:
    """Baja media, mínima y máxima, contratos e importe por grupo.

    ``filtro_base`` es un predicado SQL constante de ``db.sql_fragments``.
    ``fecha_desde``/``fecha_hasta`` acotan la fecha de adjudicación (ambas
    incluidas), ``importe_min`` el presupuesto de la licitación y ``ccaa``
    admite varias separadas por comas, como la barra global.
    """
    if group_by not in _GROUP_COLUMNS:
        raise ValueError(f"group_by inválido: {group_by!r} (válidos: {sorted(_GROUP_COLUMNS)})")
    id_col, label_col = _GROUP_COLUMNS[group_by]
    select_id = f"{id_col} AS grupo_id," if id_col else ""
    group_cols = f"{id_col}, {label_col}" if id_col else label_col

    sql = f"""
        SELECT {select_id}
               {label_col} AS grupo,
               COUNT(*) AS contratos,
               {round_sql(f"AVG({BAJA_PCT_SQL})", 2)} AS baja_media_pct,
               {round_sql(f"MIN({BAJA_PCT_SQL})", 2)} AS baja_min_pct,
               {round_sql(f"MAX({BAJA_PCT_SQL})", 2)} AS baja_max_pct,
               COALESCE(SUM(a.importe_adjudicado), 0) AS importe_total,
               {round_sql("AVG(a.n_ofertas_recibidas)", 1)} AS ofertas_medias
        FROM adjudicaciones a
        JOIN licitaciones l ON l.id_externo = a.licitacion_id
        LEFT JOIN lotes lo ON lo.id = a.lote_id
        LEFT JOIN empresas e ON e.empresa_id = a.empresa_id
        WHERE {VALID_PAIR_LOTE} AND {TECHNOLOGY_OBSERVED_SQL} AND {exclude_duplicados_sql()}
          AND {filtro_base}
    """
    params: list[object] = []
    if cpv_prefix:
        sql += " AND l.cpv LIKE %s"
        params.append(f"{cpv_prefix}%")
    ccaas = [c.strip() for c in (ccaa or "").split(",") if c.strip()]
    if len(ccaas) == 1:
        sql += " AND l.ccaa = %s"
        params.append(ccaas[0])
    elif ccaas:
        sql += " AND l.ccaa IN (" + ",".join("%s" for _ in ccaas) + ")"
        params.extend(ccaas)
    if fecha_desde is not None:
        sql += " AND a.fecha_adjudicacion >= %s"
        params.append(fecha_desde.isoformat())
    if fecha_hasta is not None:
        # Cota exclusiva al día siguiente: `fecha_adjudicacion` es texto ISO y
        # puede llevar hora, y `'2026-03-31T10:00' <= '2026-03-31'` es falso.
        sql += " AND a.fecha_adjudicacion < %s"
        params.append((fecha_hasta + timedelta(days=1)).isoformat())
    if importe_min is not None:
        sql += " AND l.importe >= %s"
        params.append(float(importe_min))
    sql += f"""
        GROUP BY {group_cols}
        HAVING COUNT(*) >= %s AND {label_col} IS NOT NULL
        ORDER BY contratos DESC
        LIMIT %s
    """
    params.extend([max(1, int(min_contratos)), max(1, min(int(limit), 500))])

    with connect_read() as c:
        return rows_to_dicts(c.execute(sql, params))


def fila_baja_de_referencia(
    *, filtro_base: str, organo: str | None, cpv_prefix: str | None
) -> dict[str, Any]:
    """Baja media y rango en un segmento (órgano y/o CPV); ``{}`` si no hay fila."""
    sql = f"""
        SELECT COUNT(*) AS contratos,
               {round_sql(f"AVG({BAJA_PCT_SQL})", 2)} AS baja_media_pct,
               {round_sql(f"MIN({BAJA_PCT_SQL})", 2)} AS baja_min_pct,
               {round_sql(f"MAX({BAJA_PCT_SQL})", 2)} AS baja_max_pct,
               {round_sql("AVG(a.n_ofertas_recibidas)", 1)} AS ofertas_medias
        FROM adjudicaciones a
        JOIN licitaciones l ON l.id_externo = a.licitacion_id
        LEFT JOIN lotes lo ON lo.id = a.lote_id
        WHERE {VALID_PAIR_LOTE} AND {TECHNOLOGY_OBSERVED_SQL} AND {exclude_duplicados_sql()}
          AND {filtro_base}
    """
    params: list[object] = []
    if organo:
        sql += " AND l.organo_contratacion = %s"
        params.append(organo)
    if cpv_prefix:
        sql += " AND l.cpv LIKE %s"
        params.append(f"{cpv_prefix}%")

    with connect_read() as c:
        rows = rows_to_dicts(c.execute(sql, params))
    return rows[0] if rows else {}


def bajas_medias_del_scoring(cutoff: str) -> tuple[dict[str, float], float | None]:
    """Baja media (fracción 0-1) por CPV-4 y global, de adjudicaciones desde ``cutoff``.

    Alimenta la señal de margen del scoring (``services.analytics.scoring_signals``).
    El denominador es el presupuesto de cada fila de adjudicación —el de su lote
    si lo tiene— vía ``BAJA_PCT_SQL``: agregar por licitación sobreestimaría la
    baja de un expediente multi-lote. Un CPV-4 necesita tres adjudicaciones para
    tener media propia, y los duplicados entre fuentes no cuentan: un mismo
    contrato llegado por PLACSP y TED pesaba doble y podía llenar solo el umbral.
    """
    sql_cpv4 = f"""
        SELECT substr(l.cpv, 1, 4) AS cpv4, AVG({BAJA_PCT_SQL} / 100) AS baja_media
        FROM adjudicaciones a
        JOIN licitaciones l ON l.id_externo = a.licitacion_id
        LEFT JOIN lotes lo ON lo.id = a.lote_id
        WHERE a.fecha_adjudicacion >= %s
          AND {TECHNOLOGY_OBSERVED_SQL}
          AND l.cpv IS NOT NULL
          AND length(l.cpv) >= 4
          AND {VALID_PAIR_LOTE}
          AND {exclude_duplicados_sql()}
        GROUP BY cpv4
        HAVING COUNT(*) >= 3
    """
    sql_global = f"""
        SELECT AVG({BAJA_PCT_SQL} / 100)
        FROM adjudicaciones a
        JOIN licitaciones l ON l.id_externo = a.licitacion_id
        LEFT JOIN lotes lo ON lo.id = a.lote_id
        WHERE a.fecha_adjudicacion >= %s
          AND {TECHNOLOGY_OBSERVED_SQL}
          AND {VALID_PAIR_LOTE}
          AND {exclude_duplicados_sql()}
    """
    with connect_read() as c:
        por_cpv4 = {
            str(cpv4): float(media)
            for cpv4, media in c.execute(sql_cpv4, (cutoff,)).fetchall()
            if cpv4 is not None and media is not None
        }
        fila = c.execute(sql_global, (cutoff,)).fetchone()
    global_ = float(fila[0]) if fila is not None and fila[0] is not None else None
    return por_cpv4, global_
