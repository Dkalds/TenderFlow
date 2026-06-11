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

# Expresión SQL reutilizable para la fecha de fin efectiva del contrato.
# substr(x, 1, 10) normaliza timestamps ISO a fecha pura; CAST a INT porque
# duracion_valor es REAL y el modificador de date() exige entero.
_FECHA_FIN_SQL = """
COALESCE(
    substr(l.fecha_fin, 1, 10),
    CASE l.duracion_unidad
        WHEN 'ANN' THEN date(substr(COALESCE(l.fecha_inicio, a.fecha_adjudicacion), 1, 10),
                             '+' || CAST(l.duracion_valor AS INTEGER) || ' years')
        WHEN 'MON' THEN date(substr(COALESCE(l.fecha_inicio, a.fecha_adjudicacion), 1, 10),
                             '+' || CAST(l.duracion_valor AS INTEGER) || ' months')
        WHEN 'DAY' THEN date(substr(COALESCE(l.fecha_inicio, a.fecha_adjudicacion), 1, 10),
                             '+' || CAST(l.duracion_valor AS INTEGER) || ' days')
    END
)
"""


def proximas_renovaciones(
    *,
    months_ahead: int = 6,
    empresa_id: int | None = None,
    ccaa: str | None = None,
    min_importe: float | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Contratos cuya fecha de fin efectiva cae en los próximos N meses.

    Cada fila es un par contrato-adjudicatario con la empresa canónica del
    maestro, ordenado por proximidad del vencimiento.
    """
    months_ahead = max(1, min(int(months_ahead), 60))
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
               {_FECHA_FIN_SQL} AS fecha_fin_efectiva,
               CAST(julianday({_FECHA_FIN_SQL}) - julianday('now') AS INTEGER) AS dias_restantes
        FROM adjudicaciones a
        JOIN licitaciones l ON l.id_externo = a.licitacion_id
        LEFT JOIN empresas e ON e.empresa_id = a.empresa_id
        WHERE {_FECHA_FIN_SQL} BETWEEN date('now')
              AND date('now', '+' || ? || ' months')
    """  # noqa: S608 — _FECHA_FIN_SQL es un fragmento constante; valores con ?
    params: list[Any] = [months_ahead]
    if empresa_id is not None:
        sql += " AND a.empresa_id = ?"
        params.append(empresa_id)
    if ccaa:
        sql += " AND l.ccaa = ?"
        params.append(ccaa)
    if min_importe is not None:
        sql += " AND a.importe_adjudicado >= ?"
        params.append(min_importe)
    sql += " ORDER BY fecha_fin_efectiva ASC LIMIT ? OFFSET ?"
    params.extend([max(1, min(int(limit), 1000)), max(0, int(offset))])

    with connect_read() as c:
        return rows_to_dicts(c.execute(sql, params))


def resumen_renovaciones(*, months_ahead: int = 12) -> list[dict[str, Any]]:
    """Vencimientos agregados por empresa para la ventana dada.

    Responde "¿qué cartera de cada competidor está en juego?": número de
    contratos e importe que vencen, con el vencimiento más próximo.
    """
    months_ahead = max(1, min(int(months_ahead), 60))
    sql = f"""
        SELECT a.empresa_id,
               COALESCE(e.nombre_canonico, a.nombre) AS empresa,
               COUNT(*) AS contratos_venciendo,
               COALESCE(SUM(a.importe_adjudicado), 0) AS importe_en_juego,
               MIN({_FECHA_FIN_SQL}) AS proximo_vencimiento
        FROM adjudicaciones a
        JOIN licitaciones l ON l.id_externo = a.licitacion_id
        LEFT JOIN empresas e ON e.empresa_id = a.empresa_id
        WHERE {_FECHA_FIN_SQL} BETWEEN date('now')
              AND date('now', '+' || ? || ' months')
        GROUP BY a.empresa_id, empresa
        ORDER BY importe_en_juego DESC
        LIMIT 100
    """  # noqa: S608 — _FECHA_FIN_SQL es un fragmento constante; valores con ?
    with connect_read() as c:
        return rows_to_dicts(c.execute(sql, [months_ahead]))
