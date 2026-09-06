"""Consultas de solo lectura para auditar la correspondencia entre el modelo
de dominio y la realidad contractual (Ola 0 del plan de corrección de verdad
del dato — ver docs/IMPROVEMENT_BACKLOG.md).

Solo lectura, sin transformación de negocio: expone números crudos que
consume ``scripts/audit_domain_truth.py``.

``_TECHNOLOGY_OBSERVED`` y ``_EXCLUDE_DUPLICADOS`` eran copias literales de
``services/sql_fragments.py``/``services/dedupe.py``, justificadas porque
``db/`` no puede depender de ``services/`` (capa superior, ADR-024). Desde que
las dos definiciones canónicas viven en ``db/sql_fragments.py`` —el lado
correcto de la frontera— esa justificación ya no existe, y aquí se importan:
una auditoría de la verdad del dato que mide sobre un universo distinto del que
mide el producto no audita nada, y una copia divergente no se ve.

``_VALID_PAIR`` sigue siendo copia: su definición canónica está en
``services/sql_fragments.py`` y no ha bajado a ``db/`` todavía.
"""

from __future__ import annotations

from typing import Any

from db.connection import connect_read
from db.repositories.base import rows_to_dicts
from db.sql_fragments import TECHNOLOGY_OBSERVED_SQL, exclude_duplicados_sql

# Espejo de services/sql_fragments.py::VALID_PAIR.
_VALID_PAIR = (
    "l.importe > 0 AND a.importe_adjudicado > 0 AND a.importe_adjudicado <= l.importe * 1.5"
)
_TECHNOLOGY_OBSERVED = TECHNOLOGY_OBSERVED_SQL
_EXCLUDE_DUPLICADOS = exclude_duplicados_sql("l.id_externo")


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
    # El total permite expresar el problema como proporción. Un conteo absoluto
    # de grupos solo crece con el histórico, así que no sirve para un umbral
    # que distinga "la ingesta empeoró" de "hay más datos que ayer".
    total_sql = """
        SELECT COUNT(*) AS total
        FROM adjudicaciones
        WHERE importe_adjudicado IS NOT NULL AND nif IS NOT NULL
    """
    with connect_read() as c:
        grupos = rows_to_dicts(c.execute(group_sql))
        total_filas = int(rows_to_dicts(c.execute(total_sql))[0]["total"])

    filas_afectadas = sum(int(g["filas"]) for g in grupos)
    return {
        "grupos_candidatos": len(grupos),
        "filas_afectadas": filas_afectadas,
        "total_filas": total_filas,
        "pct_filas_afectadas": (
            round(100.0 * filas_afectadas / total_filas, 2) if total_filas else 0.0
        ),
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


def adjudicaciones_con_fecha_imposible() -> dict[str, Any]:
    """Adjudicaciones con ``fecha_adjudicacion`` anterior al año plausible (C4.4).

    La mayoría son ``1899-12-30``: el cero de la epoch de Excel, o sea como PSCP
    exporta una celda vacía. Pasan cualquier validación de formato —cuatro
    cifras, parsean bien— y ganan el ``LEAST(fecha_publicacion,
    fecha_adjudicacion)`` que ancla el dataset de ML, así que la fila entra en el
    train de todos los folds con los acumuladores históricos vacíos.

    Desde C4.4 el conector de PSCP las corta en el origen. Esto cuenta el
    histórico ya escrito, que el conector no puede ver: sin un número que alguien
    mire, "cortado en el origen" es una afirmación sin comprobación.
    """
    from shared.dates import ANIO_MINIMO_PLAUSIBLE

    corte = f"{ANIO_MINIMO_PLAUSIBLE:04d}-01-01"
    with connect_read() as c:
        total = c.execute(
            "SELECT COUNT(*) FROM adjudicaciones "
            "WHERE fecha_adjudicacion IS NOT NULL AND fecha_adjudicacion < %s",
            (corte,),
        ).fetchone()
        por_fuente = c.execute(
            "SELECT l.fuente, COUNT(*) AS filas FROM adjudicaciones a "
            "JOIN licitaciones l ON l.id_externo = a.licitacion_id "
            "WHERE a.fecha_adjudicacion IS NOT NULL AND a.fecha_adjudicacion < %s "
            "GROUP BY l.fuente ORDER BY COUNT(*) DESC",
            (corte,),
        ).fetchall()
    return {
        "antes_de_1990": int(total[0]) if total else 0,
        "corte": corte,
        "por_fuente": [{"fuente": f, "filas": int(n)} for f, n in por_fuente],
    }


def importe_sin_base_declarada(*, desde: str) -> dict[str, Any]:
    """Filas nuevas cuyo importe no dice de qué base es (C1.1, ADR-032).

    ``desde`` es la fecha a partir de la cual una fila cuenta como "nueva": la
    de la migración ``v112``. Las anteriores están en ``desconocido`` por
    construcción —el parser guardaba el número y tiraba la información de qué
    elemento CODICE lo produjo— y exigirles una base sería exigir que el pasado
    se reescriba solo.

    El umbral es **0 sobre las nuevas**: a partir de ``v112`` toda fila con
    importe pasa por un parser que sí sabe de dónde viene. Una fila nueva sin
    tipo significa que hay un camino de escritura que no lo puebla, y ese es
    exactamente el defecto que este control busca.
    """
    with connect_read() as c:
        fila = c.execute(
            "SELECT COUNT(*) FILTER (WHERE importe IS NOT NULL) AS con_importe, "
            "  COUNT(*) FILTER (WHERE importe IS NOT NULL AND importe_tipo IS NULL) "
            "    AS sin_tipo, "
            "  COUNT(*) FILTER (WHERE importe_tipo = 'desconocido') AS desconocido, "
            "  COUNT(*) FILTER (WHERE importe_base_sin_iva IS NOT NULL) AS con_base "
            "FROM licitaciones "
            "WHERE COALESCE(primera_extraccion, fecha_extraccion) >= %s",
            (desde,),
        ).fetchone()
    if not fila:
        return {"desde": desde, "con_importe": 0, "sin_tipo": 0, "desconocido": 0, "con_base": 0}
    return {
        "desde": desde,
        "con_importe": int(fila[0] or 0),
        "sin_tipo": int(fila[1] or 0),
        "desconocido": int(fila[2] or 0),
        "con_base": int(fila[3] or 0),
    }
