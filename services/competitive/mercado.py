"""Cuota de mercado, concentración (HHI) y presión competitiva.

Todas las métricas se calculan sobre empresas canónicas del maestro (v35),
no sobre strings de nombre — sin eso las cuotas estarían fragmentadas entre
variantes del mismo adjudicatario.
"""

from __future__ import annotations

from typing import Any

from db.database import connect_read
from db.repositories.base import rows_to_dicts
from services.dedupe import exclude_duplicados_sql

_SEGMENT_COLUMNS = {
    "cpv": "substr(l.cpv, 1, 2)",
    "ccaa": "l.ccaa",
    "organo": "l.organo_contratacion",
    "tecnologia": "l.tecnologia",
}


def cuota_mercado(
    *,
    cpv_prefix: str | None = None,
    ccaa: str | None = None,
    desde: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Ranking de empresas por importe adjudicado con cuota % del segmento.

    La presión competitiva media (``ofertas_medias``) contextualiza la cuota:
    dominar un segmento con 1.2 ofertas medias no es lo mismo que con 8.
    """
    filters = ""
    params: list[Any] = []
    if cpv_prefix:
        filters += " AND l.cpv LIKE ?"
        params.append(f"{cpv_prefix}%")
    if ccaa:
        filters += " AND l.ccaa = ?"
        params.append(ccaa)
    if desde:
        filters += " AND a.fecha_adjudicacion >= ?"
        params.append(desde)

    sql = f"""
        WITH segmento AS (
            SELECT a.empresa_id,
                   COALESCE(e.nombre_canonico, a.nombre) AS empresa,
                   MAX(COALESCE(e.es_ute, 0)) AS es_ute,
                   COUNT(*) AS contratos,
                   COALESCE(SUM(a.importe_adjudicado), 0) AS importe,
                   ROUND(AVG(a.n_ofertas_recibidas), 1) AS ofertas_medias
            FROM adjudicaciones a
            JOIN licitaciones l ON l.id_externo = a.licitacion_id
            LEFT JOIN empresas e ON e.empresa_id = a.empresa_id
            WHERE a.importe_adjudicado > 0 AND {exclude_duplicados_sql()} {filters}
            GROUP BY a.empresa_id, empresa
        )
        SELECT empresa_id, empresa, es_ute, contratos, importe, ofertas_medias,
               ROUND(importe * 100.0 / NULLIF((SELECT SUM(importe) FROM segmento), 0), 2)
                   AS cuota_pct
        FROM segmento
        ORDER BY importe DESC
        LIMIT ?
    """  # noqa: S608 — filters se construye solo con fragmentos constantes; valores con ?
    params.append(max(1, min(int(limit), 500)))
    with connect_read() as c:
        return rows_to_dicts(c.execute(sql, params))


def concentracion_hhi(*, segment_by: str = "cpv", min_contratos: int = 5) -> list[dict[str, Any]]:
    """Índice Herfindahl-Hirschman por segmento (0-10000).

    HHI = suma de (cuota_i * 100)^2. Lectura estándar: <1500 competitivo,
    1500-2500 moderadamente concentrado, >2500 concentrado. Un segmento
    concentrado con vencimientos próximos es una oportunidad de entrada;
    uno competitivo exige afinar la baja (ver ``bajas``).
    """
    if segment_by not in _SEGMENT_COLUMNS:
        raise ValueError(
            f"segment_by inválido: {segment_by!r} (válidos: {sorted(_SEGMENT_COLUMNS)})"
        )
    seg_col = _SEGMENT_COLUMNS[segment_by]

    sql = f"""
        WITH por_empresa AS (
            SELECT {seg_col} AS segmento,
                   a.empresa_id,
                   SUM(a.importe_adjudicado) AS importe
            FROM adjudicaciones a
            JOIN licitaciones l ON l.id_externo = a.licitacion_id
            WHERE a.importe_adjudicado > 0 AND {seg_col} IS NOT NULL
              AND {exclude_duplicados_sql()}
            GROUP BY segmento, a.empresa_id
        ),
        totales AS (
            SELECT segmento,
                   SUM(importe) AS total,
                   COUNT(*) AS empresas
            FROM por_empresa GROUP BY segmento
        )
        SELECT p.segmento,
               t.empresas,
               t.total AS importe_total,
               (SELECT COUNT(*) FROM adjudicaciones a2
                JOIN licitaciones l2 ON l2.id_externo = a2.licitacion_id
                WHERE {seg_col.replace("l.", "l2.")} = p.segmento
                  AND a2.importe_adjudicado > 0
                  AND {exclude_duplicados_sql("l2.id_externo")}) AS contratos,
               ROUND(SUM((p.importe * 100.0 / t.total) * (p.importe * 100.0 / t.total)), 0)
                   AS hhi
        FROM por_empresa p
        JOIN totales t ON t.segmento = p.segmento
        GROUP BY p.segmento
        HAVING contratos >= ?
        ORDER BY hhi DESC
    """  # noqa: S608 — seg_col sale de _SEGMENT_COLUMNS (whitelist); valores con ?
    with connect_read() as c:
        return rows_to_dicts(c.execute(sql, [max(1, int(min_contratos))]))


def perfil_empresa(empresa_id: int) -> dict[str, Any]:
    """Perfil competitivo de una empresa: dónde gana, contra cuánta presión.

    Pensado para la ficha de competidor del frontend: totales, desglose por
    CPV-2 y CCAA, y presión competitiva media en sus adjudicaciones.
    """
    with connect_read() as c:
        totales = rows_to_dicts(
            c.execute(
                f"""
                SELECT COUNT(*) AS contratos,
                       COALESCE(SUM(a.importe_adjudicado), 0) AS importe_total,
                       ROUND(AVG(a.n_ofertas_recibidas), 1) AS ofertas_medias,
                       MIN(a.fecha_adjudicacion) AS primera_adjudicacion,
                       MAX(a.fecha_adjudicacion) AS ultima_adjudicacion
                FROM adjudicaciones a
                WHERE a.empresa_id = ? AND {exclude_duplicados_sql("a.licitacion_id")}
                """,  # noqa: S608 — fragmento constante de services.dedupe; valores con ?
                (empresa_id,),
            )
        )
        por_cpv = rows_to_dicts(
            c.execute(
                f"""
                SELECT substr(l.cpv, 1, 2) AS cpv2,
                       COUNT(*) AS contratos,
                       COALESCE(SUM(a.importe_adjudicado), 0) AS importe
                FROM adjudicaciones a
                JOIN licitaciones l ON l.id_externo = a.licitacion_id
                WHERE a.empresa_id = ? AND l.cpv IS NOT NULL
                  AND {exclude_duplicados_sql()}
                GROUP BY cpv2 ORDER BY importe DESC LIMIT 10
                """,  # noqa: S608 — fragmento constante de services.dedupe; valores con ?
                (empresa_id,),
            )
        )
        por_ccaa = rows_to_dicts(
            c.execute(
                f"""
                SELECT l.ccaa,
                       COUNT(*) AS contratos,
                       COALESCE(SUM(a.importe_adjudicado), 0) AS importe
                FROM adjudicaciones a
                JOIN licitaciones l ON l.id_externo = a.licitacion_id
                WHERE a.empresa_id = ? AND l.ccaa IS NOT NULL
                  AND {exclude_duplicados_sql()}
                GROUP BY l.ccaa ORDER BY importe DESC LIMIT 20
                """,  # noqa: S608 — fragmento constante de services.dedupe; valores con ?
                (empresa_id,),
            )
        )
        organos = rows_to_dicts(
            c.execute(
                f"""
                SELECT l.organo_contratacion AS organo,
                       COUNT(*) AS contratos,
                       COALESCE(SUM(a.importe_adjudicado), 0) AS importe
                FROM adjudicaciones a
                JOIN licitaciones l ON l.id_externo = a.licitacion_id
                WHERE a.empresa_id = ? AND l.organo_contratacion IS NOT NULL
                  AND {exclude_duplicados_sql()}
                GROUP BY organo ORDER BY importe DESC LIMIT 10
                """,  # noqa: S608 — fragmento constante de services.dedupe; valores con ?
                (empresa_id,),
            )
        )
        por_anio = rows_to_dicts(
            c.execute(
                f"""
                SELECT CAST(strftime('%Y', a.fecha_adjudicacion) AS INTEGER) AS anio,
                       COUNT(*) AS contratos,
                       COALESCE(SUM(a.importe_adjudicado), 0) AS importe
                FROM adjudicaciones a
                WHERE a.empresa_id = ? AND a.fecha_adjudicacion IS NOT NULL
                  AND {exclude_duplicados_sql("a.licitacion_id")}
                GROUP BY anio HAVING anio IS NOT NULL ORDER BY anio
                """,  # noqa: S608 — fragmento constante de services.dedupe; valores con ?
                (empresa_id,),
            )
        )
        contratos_recientes = rows_to_dicts(
            c.execute(
                f"""
                SELECT a.licitacion_id,
                       l.titulo,
                       l.organo_contratacion,
                       a.fecha_adjudicacion,
                       a.importe_adjudicado
                FROM adjudicaciones a
                LEFT JOIN licitaciones l ON l.id_externo = a.licitacion_id
                WHERE a.empresa_id = ?
                  AND {exclude_duplicados_sql("a.licitacion_id")}
                ORDER BY a.fecha_adjudicacion DESC
                LIMIT 12
                """,  # noqa: S608 — fragmento constante de services.dedupe; valores con ?
                (empresa_id,),
            )
        )
    return {
        "empresa_id": empresa_id,
        "totales": totales[0] if totales else {},
        "por_cpv": por_cpv,
        "por_ccaa": por_ccaa,
        "organos_principales": organos,
        "por_anio": por_anio,
        "contratos_recientes": contratos_recientes,
    }
