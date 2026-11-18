"""Lecturas de los monitores del scheduler sobre ``licitaciones`` y ``adjudicaciones``.

Las consultas de ``scheduler/anomaly_alerts.py`` (importe anómalo, baja
temeraria, spike de publicaciones), ``scheduler/concept_drift.py`` (textos
recientes) y la deriva de ``ml_proba`` de ``scheduler/drift_report.py``. El
cálculo (medias, umbrales, tests estadísticos) se queda en el scheduler; aquí
solo el SQL (ADR-022).

Abren conexión de escritura (``connect``) como hacían en el scheduler, salvo
la deriva de ``ml_proba``, que ya leía por ``connect_read``.
"""

from __future__ import annotations

from db.database import connect, connect_read


def importes_del_organo(organo: str, meses: int) -> list[float]:
    """Importes no nulos del órgano publicados en los últimos ``meses`` meses."""
    with connect() as c:
        filas = c.execute(
            "SELECT importe FROM licitaciones "
            "WHERE organo_contratacion = %s "
            "  AND fecha_publicacion >= to_char(CURRENT_DATE - (%s * INTERVAL '1 month'), 'YYYY-MM-DD') "
            "  AND importe IS NOT NULL",
            (organo, meses),
        ).fetchall()
    return [row[0] for row in filas if row[0] is not None]


def licitaciones_ultimas_24h() -> list[dict[str, object]]:
    """Licitaciones publicadas en las últimas 24 horas, la más reciente primero."""
    with connect() as c:
        cur = c.execute(
            "SELECT id_externo, titulo, organo_contratacion, importe, cpv, url "
            "FROM licitaciones "
            "WHERE fecha_publicacion >= to_char(NOW() - INTERVAL '1 day', 'YYYY-MM-DD HH24:MI:SS') "
            "ORDER BY fecha_publicacion DESC",
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def adjudicaciones_ultimas_24h() -> list[dict[str, object]]:
    """Adjudicaciones del último día con importe adjudicado y de licitación (para la baja)."""
    with connect() as c:
        cur = c.execute(
            "SELECT a.id, a.licitacion_id, a.nombre, a.importe_adjudicado, "
            "       l.importe AS importe_licitacion, l.titulo, l.organo_contratacion "
            "FROM adjudicaciones a "
            "JOIN licitaciones l ON l.id_externo = a.licitacion_id "
            "WHERE a.fecha_adjudicacion >= to_char(CURRENT_DATE - INTERVAL '1 day', 'YYYY-MM-DD') "
            "  AND a.importe_adjudicado IS NOT NULL "
            "  AND l.importe IS NOT NULL AND l.importe > 0",
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def publicadas_en_los_ultimos_dias(dias: int) -> int:
    """Licitaciones con ``fecha_publicacion`` desde hace ``dias`` días (por fecha, sin hora)."""
    with connect() as c:
        fila = c.execute(
            "SELECT COUNT(*) FROM licitaciones WHERE fecha_publicacion >= "
            "to_char(CURRENT_DATE - (%s * INTERVAL '1 day'), 'YYYY-MM-DD')",
            (dias,),
        ).fetchone()
    return int(fila[0] or 0)


def textos_recientes(desde_iso: str) -> list[tuple[str | None, str | None]]:
    """``(titulo, descripcion)`` publicadas desde ``desde_iso``, sin el universo CPV sin señal.

    Fuera el universo CPV sin señal (``cpv_ti_universe``): el detector de
    deriva busca términos emergentes entre lo que el diccionario ya acepta, y
    meter todo el CPV 48/72 sólo lo llenaría de vocabulario genérico de TI
    («mantenimiento», «licencias») que no es deriva.
    """
    with connect() as c:
        filas = c.execute(
            "SELECT titulo, descripcion FROM licitaciones WHERE fecha_publicacion >= %s "
            "AND COALESCE(inclusion_reason, '') <> 'cpv_ti_universe'",
            (desde_iso,),
        ).fetchall()
    return [(row[0], row[1]) for row in filas]


def ml_proba_por_ventana(reciente_desde: str, previa_desde: str) -> tuple[list[float], list[float]]:
    """``ml_proba`` no nulas de dos ventanas: ``[reciente_desde, ∞)`` y ``[previa_desde, reciente_desde)``."""
    with connect_read() as conn:
        recientes = conn.execute(
            "SELECT ml_proba FROM licitaciones "
            "WHERE fecha_publicacion >= %s AND ml_proba IS NOT NULL",
            (reciente_desde,),
        ).fetchall()
        previas = conn.execute(
            "SELECT ml_proba FROM licitaciones "
            "WHERE fecha_publicacion >= %s AND fecha_publicacion < %s AND ml_proba IS NOT NULL",
            (previa_desde, reciente_desde),
        ).fetchall()
    return (
        [float(r[0]) for r in recientes if r[0] is not None],
        [float(r[0]) for r in previas if r[0] is not None],
    )
