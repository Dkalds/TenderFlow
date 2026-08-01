"""Consultas de solo lectura para auditar la correspondencia entre el modelo
de dominio y la realidad contractual (Ola 0 del plan de corrección de verdad
del dato — ver docs/IMPROVEMENT_BACKLOG.md).

Solo lectura, sin transformación de negocio: expone números crudos que
consume ``scripts/audit_domain_truth.py``. Los fragmentos WHERE
(``_VALID_PAIR``, ``_TECHNOLOGY_OBSERVED``, ``_EXCLUDE_DUPLICADOS``) espejan
deliberadamente ``services/sql_fragments.py``/``services/dedupe.py``:
duplicados aquí porque ``db/`` no debe depender de ``services/`` (capa
superior, ADR-024) — no porque el criterio de negocio sea distinto.
"""

from __future__ import annotations

from typing import Any

from db.connection import connect_read
from db.repositories.base import rows_to_dicts

# Espejo de services/sql_fragments.py::VALID_PAIR.
_VALID_PAIR = (
    "l.importe > 0 AND a.importe_adjudicado > 0 AND a.importe_adjudicado <= l.importe * 1.5"
)
# Espejo de services/sql_fragments.py::TECHNOLOGY_OBSERVED_SQL.
_TECHNOLOGY_OBSERVED = (
    "COALESCE(l.analysis_universe, 'technology_observed') = 'technology_observed'"
)
# Espejo de services/dedupe.py::exclude_duplicados_sql() para col="l.id_externo".
_EXCLUDE_DUPLICADOS = (
    "l.id_externo NOT IN "
    "(SELECT licitacion_id FROM licitaciones_duplicados WHERE status = 'confirmed')"
)


def fecha_limite_gap_by_source() -> list[dict[str, Any]]:
    """% de licitaciones sin ``fecha_limite``, por fuente de ingesta.

    Antes del fix de Ola 1, PLACSP (fuente por defecto) debería mostrar
    ~100% — el parser nunca extraía el campo. Sirve como medida directa del
    efecto del fix: repetir tras un backfill y comparar.
    """
    sql = """
        SELECT fuente,
               COUNT(*) AS total,
               COUNT(*) FILTER (WHERE fecha_limite IS NULL) AS sin_fecha_limite,
               ROUND(
                   100.0 * COUNT(*) FILTER (WHERE fecha_limite IS NULL)
                   / NULLIF(COUNT(*), 0),
                   1
               ) AS pct_sin_fecha_limite
        FROM licitaciones
        GROUP BY fuente
        ORDER BY total DESC
    """
    with connect_read() as c:
        return rows_to_dicts(c.execute(sql))


def ute_candidate_stats(sample_size: int = 10) -> dict[str, Any]:
    """Adjudicaciones que comparten ``(licitacion_id, fecha_adjudicacion,
    importe_adjudicado)`` con distinto NIF.

    Proxy de UTE modelada hoy como N filas con el importe íntegro repetido
    (una por ``WinningParty``) en vez de una fila de adjudicación + N
    miembros con reparto — cada fila de un grupo infla el importe atribuido
    al segmento cuando se agrega por empresa (cuota, HHI).
    """
    group_sql = """
        SELECT licitacion_id, fecha_adjudicacion, importe_adjudicado,
               COUNT(DISTINCT nif) AS empresas_distintas,
               COUNT(*) AS filas
        FROM adjudicaciones
        WHERE importe_adjudicado IS NOT NULL AND nif IS NOT NULL
        GROUP BY licitacion_id, fecha_adjudicacion, importe_adjudicado
        HAVING COUNT(DISTINCT nif) > 1
        ORDER BY filas DESC
    """
    with connect_read() as c:
        grupos = rows_to_dicts(c.execute(group_sql))

    return {
        "grupos_candidatos": len(grupos),
        "filas_afectadas": sum(int(g["filas"]) for g in grupos),
        "muestra": grupos[:sample_size],
    }


def baja_media_delta() -> dict[str, Any]:
    """Compara ``baja_media_pct`` por-adjudicación (cálculo hoy en
    ``services/competitive/bajas.py``) contra la misma métrica agregada por
    licitación (patrón ya usado en ``services/ml/calibration.py`` y
    ``services/ml/scoring.py``).

    La diferencia entre ambas es el efecto del bug multi-lote: sin agregar
    por licitación, un expediente con varios lotes compara cada lote contra
    el presupuesto TOTAL del expediente, inflando la baja calculada.
    """
    per_adjudicacion_sql = f"""
        SELECT AVG((l.importe - a.importe_adjudicado) / l.importe * 100) AS baja_media_pct,
               COUNT(*) AS n
        FROM adjudicaciones a
        JOIN licitaciones l ON l.id_externo = a.licitacion_id
        WHERE {_VALID_PAIR} AND {_TECHNOLOGY_OBSERVED} AND {_EXCLUDE_DUPLICADOS}
    """
    per_licitacion_sql = f"""
        WITH agregado AS (
            SELECT a.licitacion_id AS lic_id, SUM(a.importe_adjudicado) AS total_adjudicado
            FROM adjudicaciones a
            WHERE a.importe_adjudicado > 0
            GROUP BY a.licitacion_id
        )
        SELECT AVG((l.importe - ag.total_adjudicado) / l.importe * 100) AS baja_media_pct,
               COUNT(*) AS n
        FROM agregado ag
        JOIN licitaciones l ON l.id_externo = ag.lic_id
        WHERE l.importe > 0
          AND ag.total_adjudicado <= l.importe * 1.5
          AND {_TECHNOLOGY_OBSERVED} AND {_EXCLUDE_DUPLICADOS}
    """
    with connect_read() as c:
        per_adjudicacion = rows_to_dicts(c.execute(per_adjudicacion_sql))[0]
        per_licitacion = rows_to_dicts(c.execute(per_licitacion_sql))[0]

    return {
        "baja_media_pct_por_adjudicacion": per_adjudicacion["baja_media_pct"],
        "n_por_adjudicacion": per_adjudicacion["n"],
        "baja_media_pct_por_licitacion": per_licitacion["baja_media_pct"],
        "n_por_licitacion": per_licitacion["n"],
    }
