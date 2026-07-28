"""Pipeline de renovaciones: contratos adjudicados que vencen próximamente.

La fecha de fin efectiva se calcula en SQL con esta prioridad:

1. ``licitaciones.fecha_fin`` explícita (solo ~6% de las filas).
2. ``fecha_inicio + duracion`` (unidades CODICE: ANN/MON/DAY).
3. ``fecha_adjudicacion + duracion`` como último recurso.

Un contrato que vence es una oportunidad: o lo defiende el adjudicatario
actual o se lo disputa quien llegue primero a la relicitación.
"""

from __future__ import annotations

from typing import Any

from db.database import connect_read
from db.repositories.base import rows_to_dicts
from services.dedupe import exclude_duplicados_sql

# FECHA_FIN_SQL se re-exporta por compatibilidad con imports externos (asume
# SQLite). Código nuevo debe usar fecha_fin_sql() (backend-aware, ADR-016).
from services.sql_fragments import FECHA_FIN_SQL, fecha_fin_sql  # noqa: F401


def _rango_vencimiento_sql() -> str:
    """``BETWEEN`` de vencimiento: hoy y hoy + N meses (parámetro ``?``).

    Produce TEXT 'YYYY-MM-DD' para comparar contra ``fecha_fin_sql()``, que
    usa el mismo formato.
    """
    return (
        "BETWEEN to_char(CURRENT_DATE, 'YYYY-MM-DD') "
        "AND to_char(CURRENT_DATE + (? * INTERVAL '1 month'), 'YYYY-MM-DD')"
    )


def _dias_restantes_sql(fecha_fin_expr: str) -> str:
    """Días restantes hasta el vencimiento, como entero."""
    return f"(({fecha_fin_expr})::date - CURRENT_DATE)"


def proximas_renovaciones(
    *,
    months_ahead: int = 6,
    empresa_id: int | None = None,
    ccaa: str | None = None,
    tecnologias: list[str] | None = None,
    min_importe: float | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Contratos cuya fecha de fin efectiva cae en los próximos N meses.

    Cada fila es un par contrato-adjudicatario con la empresa canónica del
    maestro, ordenado por proximidad del vencimiento.
    """
    months_ahead = max(1, min(int(months_ahead), 60))
    fecha_fin = fecha_fin_sql()
    sql = f"""
        SELECT a.licitacion_id,
               l.titulo,
               l.organo_contratacion,
               l.cpv,
               l.ccaa,
               l.url,
               a.empresa_id,
               COALESCE(e.nombre_canonico, a.nombre) AS empresa,
               e.es_ute,
               a.importe_adjudicado,
               a.fecha_adjudicacion,
               l.duracion_valor,
               l.duracion_unidad,
               {fecha_fin} AS fecha_fin_efectiva,
               {_dias_restantes_sql(fecha_fin)} AS dias_restantes,
               pr.riesgo_cambio,
               pr.model_version AS retencion_model_version
        FROM adjudicaciones a
        JOIN licitaciones l ON l.id_externo = a.licitacion_id
        LEFT JOIN empresas e ON e.empresa_id = a.empresa_id
        LEFT JOIN predicciones_retencion pr ON pr.licitacion_id = a.licitacion_id
        WHERE {fecha_fin} {_rango_vencimiento_sql()}
          AND {exclude_duplicados_sql()}
    """  # noqa: S608 — fragmentos constantes de services.sql_fragments; valores con ?
    params: list[Any] = [months_ahead]
    if empresa_id is not None:
        sql += " AND a.empresa_id = ?"
        params.append(empresa_id)
    if ccaa:
        sql += " AND l.ccaa = ?"
        params.append(ccaa)
    tecnologias = [t for t in (tecnologias or []) if t]
    if tecnologias:
        placeholders = ",".join("?" for _ in tecnologias)
        sql += f" AND l.tecnologia IN ({placeholders})"
        params.extend(tecnologias)
    if min_importe is not None:
        sql += " AND a.importe_adjudicado >= ?"
        params.append(min_importe)
    sql += " ORDER BY fecha_fin_efectiva ASC LIMIT ? OFFSET ?"
    params.extend([max(1, min(int(limit), 1000)), max(0, int(offset))])

    with connect_read() as c:
        return rows_to_dicts(c.execute(sql, params))


def resumen_renovaciones(
    *,
    months_ahead: int = 12,
    tecnologias: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Vencimientos agregados por empresa para la ventana dada.

    Responde "¿qué cartera de cada competidor está en juego?": número de
    contratos e importe que vencen, con el vencimiento más próximo.
    """
    months_ahead = max(1, min(int(months_ahead), 60))
    fecha_fin = fecha_fin_sql()
    sql = f"""
        SELECT a.empresa_id,
               COALESCE(e.nombre_canonico, a.nombre) AS empresa,
               COUNT(*) AS contratos_venciendo,
               COALESCE(SUM(a.importe_adjudicado), 0) AS importe_en_juego,
               MIN({fecha_fin}) AS proximo_vencimiento
        FROM adjudicaciones a
        JOIN licitaciones l ON l.id_externo = a.licitacion_id
        LEFT JOIN empresas e ON e.empresa_id = a.empresa_id
        WHERE {fecha_fin} {_rango_vencimiento_sql()}
          AND {exclude_duplicados_sql()}
    """  # noqa: S608 — fragmentos constantes de services.sql_fragments; valores con ?
    params: list[Any] = [months_ahead]
    tecnologias = [t for t in (tecnologias or []) if t]
    if tecnologias:
        placeholders = ",".join("?" for _ in tecnologias)
        sql += f" AND l.tecnologia IN ({placeholders})"
        params.extend(tecnologias)
    sql += """
        GROUP BY a.empresa_id, empresa
        ORDER BY importe_en_juego DESC
        LIMIT 100
    """
    with connect_read() as c:
        return rows_to_dicts(c.execute(sql, params))


def totales_renovaciones(
    *,
    months_ahead: int = 6,
    tecnologias: list[str] | None = None,
) -> dict[str, Any]:
    """Totales agregados (sin GROUP BY) de contratos que vencen en la ventana.

    Pensado para banners/resúmenes que necesitan un par de cifras del dataset
    completo, sin traer ni truncar la lista de contratos en el cliente.
    """
    months_ahead = max(1, min(int(months_ahead), 60))
    fecha_fin = fecha_fin_sql()
    sql = f"""
        SELECT COUNT(*) AS contratos_venciendo,
               COALESCE(SUM(a.importe_adjudicado), 0) AS importe_en_juego
        FROM adjudicaciones a
        JOIN licitaciones l ON l.id_externo = a.licitacion_id
        WHERE {fecha_fin} {_rango_vencimiento_sql()}
          AND {exclude_duplicados_sql()}
    """  # noqa: S608 — fragmentos constantes de services.sql_fragments; valores con ?
    params: list[Any] = [months_ahead]
    tecnologias = [t for t in (tecnologias or []) if t]
    if tecnologias:
        placeholders = ",".join("?" for _ in tecnologias)
        sql += f" AND l.tecnologia IN ({placeholders})"
        params.extend(tecnologias)
    with connect_read() as c:
        rows = rows_to_dicts(c.execute(sql, params))
    return rows[0] if rows else {"contratos_venciendo": 0, "importe_en_juego": 0}
