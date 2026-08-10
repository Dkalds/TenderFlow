"""Job de pre-cálculo de KPIs — se ejecuta tras cada scraping.

Calcula métricas clave sobre las licitaciones y las persiste en la tabla
``kpi_snapshots``. Los consumidores pueden leer estos snapshots en vez de
recalcular sobre el DataFrame completo en cada ejecución.

También puede exportar agregados materializados a Parquet usando
:mod:`db.analytics` (DuckDB opcional) para análisis offline (F2).

Uso:
    python -m scheduler.kpi_precompute                    # Ejecuta el cálculo
    python -m scheduler.kpi_precompute --latest           # Muestra el último snapshot
    python -m scheduler.kpi_precompute --export-parquet   # Exporta agregados Parquet
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)


# ── Definición de KPIs a pre-calcular ────────────────────────────────────────


def _compute_all_kpis(conn: Any) -> list[dict[str, Any]]:
    """Calcula todos los KPIs desde la BD directamente.

    Returns:
        Lista de {metrica, dimension, valor, valor_text}.
    """
    snapshots: list[dict[str, Any]] = []
    now = datetime.now(UTC).isoformat()

    # ── Métricas globales ─────────────────────────────────────────────────

    # Total de licitaciones
    row = conn.execute(
        "SELECT COUNT(*) FROM licitaciones "
        "WHERE COALESCE(analysis_universe, 'technology_observed') = 'technology_observed'"
    ).fetchone()
    snapshots.append({"metrica": "total_licitaciones", "dimension": "global", "valor": row[0]})

    # Importe total y medio
    row = conn.execute(
        "SELECT SUM(importe), AVG(importe) FROM licitaciones WHERE importe IS NOT NULL "
        "AND COALESCE(analysis_universe, 'technology_observed') = 'technology_observed'"
    ).fetchone()
    snapshots.append({"metrica": "importe_total", "dimension": "global", "valor": row[0] or 0.0})
    snapshots.append({"metrica": "importe_medio", "dimension": "global", "valor": row[1] or 0.0})

    # Órganos distintos
    row = conn.execute(
        "SELECT COUNT(DISTINCT organo_contratacion) FROM licitaciones "
        "WHERE organo_contratacion IS NOT NULL "
        "AND COALESCE(analysis_universe, 'technology_observed') = 'technology_observed'"
    ).fetchone()
    snapshots.append({"metrica": "n_organos", "dimension": "global", "valor": row[0]})

    # CCAA distintas
    row = conn.execute(
        "SELECT COUNT(DISTINCT ccaa) FROM licitaciones WHERE ccaa IS NOT NULL "
        "AND COALESCE(analysis_universe, 'technology_observed') = 'technology_observed'"
    ).fetchone()
    snapshots.append({"metrica": "n_ccaa", "dimension": "global", "valor": row[0]})

    # Licitaciones últimos 30 días
    row = conn.execute(
        "SELECT COUNT(*) FROM licitaciones WHERE fecha_publicacion >= "
        "to_char(CURRENT_DATE - INTERVAL '30 days', 'YYYY-MM-DD') "
        "AND COALESCE(analysis_universe, 'technology_observed') = 'technology_observed'"
    ).fetchone()
    snapshots.append({"metrica": "licitaciones_30d", "dimension": "global", "valor": row[0]})

    # Licitaciones 30d anteriores (para delta)
    row = conn.execute(
        "SELECT COUNT(*) FROM licitaciones "
        "WHERE fecha_publicacion >= to_char(CURRENT_DATE - INTERVAL '60 days', 'YYYY-MM-DD') "
        "  AND fecha_publicacion < to_char(CURRENT_DATE - INTERVAL '30 days', 'YYYY-MM-DD') "
        "  AND COALESCE(analysis_universe, 'technology_observed') = 'technology_observed'"
    ).fetchone()
    snapshots.append({"metrica": "licitaciones_30d_prev", "dimension": "global", "valor": row[0]})

    # ── Por CCAA ──────────────────────────────────────────────────────────

    rows = conn.execute(
        "SELECT ccaa, COUNT(*) as n, SUM(importe) as total "
        "FROM licitaciones WHERE ccaa IS NOT NULL "
        "AND COALESCE(analysis_universe, 'technology_observed') = 'technology_observed' "
        "GROUP BY ccaa ORDER BY n DESC"
    ).fetchall()
    ccaa_data = [{"ccaa": r[0], "n": r[1], "importe": r[2]} for r in rows]
    snapshots.append(
        {
            "metrica": "licitaciones_por_ccaa",
            "dimension": "global",
            "valor": None,
            "valor_text": json.dumps(ccaa_data, ensure_ascii=False),
        }
    )

    # ── Por estado ────────────────────────────────────────────────────────

    rows = conn.execute(
        "SELECT estado, COUNT(*) FROM licitaciones WHERE estado IS NOT NULL "
        "AND COALESCE(analysis_universe, 'technology_observed') = 'technology_observed' "
        "GROUP BY estado ORDER BY 2 DESC"
    ).fetchall()
    estado_data = {r[0]: r[1] for r in rows}
    snapshots.append(
        {
            "metrica": "licitaciones_por_estado",
            "dimension": "global",
            "valor": None,
            "valor_text": json.dumps(estado_data, ensure_ascii=False),
        }
    )

    # ── Adjudicaciones ────────────────────────────────────────────────────

    row = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT a.licitacion_id) FROM adjudicaciones a "
        "JOIN licitaciones l ON l.id_externo = a.licitacion_id "
        "WHERE COALESCE(l.analysis_universe, 'technology_observed') = 'technology_observed'"
    ).fetchone()
    snapshots.append({"metrica": "total_adjudicaciones", "dimension": "global", "valor": row[0]})
    snapshots.append({"metrica": "licitaciones_con_adj", "dimension": "global", "valor": row[1]})

    # Top 10 adjudicatarios por importe
    rows = conn.execute(
        "SELECT a.nombre, COUNT(*) as n, SUM(a.importe_adjudicado) as total "
        "FROM adjudicaciones a JOIN licitaciones l ON l.id_externo = a.licitacion_id "
        "WHERE a.nombre IS NOT NULL AND a.importe_adjudicado IS NOT NULL "
        "AND COALESCE(l.analysis_universe, 'technology_observed') = 'technology_observed' "
        "GROUP BY a.nombre ORDER BY total DESC LIMIT 10"
    ).fetchall()
    top_adj = [{"nombre": r[0], "n": r[1], "importe": r[2]} for r in rows]
    snapshots.append(
        {
            "metrica": "top10_adjudicatarios",
            "dimension": "global",
            "valor": None,
            "valor_text": json.dumps(top_adj, ensure_ascii=False),
        }
    )

    # ── Serie mensual últimos 24 meses ────────────────────────────────────

    rows = conn.execute(
        "SELECT to_char(fecha_publicacion::date, 'YYYY-MM') as mes, "
        "       COUNT(*) as n, SUM(importe) as total "
        "FROM licitaciones "
        "WHERE fecha_publicacion >= to_char(CURRENT_DATE - INTERVAL '24 months', 'YYYY-MM-DD') "
        "AND COALESCE(analysis_universe, 'technology_observed') = 'technology_observed' "
        "GROUP BY mes ORDER BY mes"
    ).fetchall()
    serie = [{"mes": r[0], "n": r[1], "importe": r[2]} for r in rows]
    snapshots.append(
        {
            "metrica": "serie_mensual_24m",
            "dimension": "global",
            "valor": None,
            "valor_text": json.dumps(serie, ensure_ascii=False),
        }
    )

    # Añadir timestamp a todos
    for s in snapshots:
        s.setdefault("valor_text", None)
        s["computed_at"] = now

    return snapshots


def _persist_snapshots(conn: Any, snapshots: list[dict[str, Any]]) -> int:
    """Inserta los snapshots en la BD. Devuelve el número de filas insertadas."""
    conn.execute(
        "DELETE FROM kpi_snapshots"  # Limpiar todos antes de insertar nuevo snapshot completo
    )
    if not snapshots:
        return 0
    rows = [
        (s["computed_at"], s["metrica"], s["dimension"], s.get("valor"), s.get("valor_text"))
        for s in snapshots
    ]
    # executemany: una sola sentencia en vez de N round-trips a SQLite.
    conn.executemany(
        "INSERT INTO kpi_snapshots (computed_at, metrica, dimension, valor, valor_text) "
        "VALUES (%s, %s, %s, %s, %s)",
        rows,
    )
    return len(rows)


def run_kpi_precompute() -> dict[str, Any]:
    """Ejecuta el pre-cálculo completo de KPIs y los persiste en la BD.

    Returns:
        Resumen con n_metricas calculadas y tiempo de ejecución.
    """
    import time

    from db.database import connect, init_db

    t0 = time.monotonic()
    init_db()

    with connect() as c:
        snapshots = _compute_all_kpis(c)
        n = _persist_snapshots(c, snapshots)

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    log.info("kpi_precompute.done", n_metricas=n, elapsed_ms=elapsed_ms)
    return {"n_metricas": n, "elapsed_ms": elapsed_ms}


# ── Exportación Parquet materializada (F2) ────────────────────────────────────

_MAT_QUERIES: dict[str, str] = {
    # `substr` y no `strftime`: esta consulta la ejecuta DuckDB sólo si el
    # extra `[analytics]` está instalado; sin él —el caso de la imagen que se
    # despliega, `requirements.txt` no trae duckdb— cae al fallback de pandas
    # contra Postgres, que no tiene `strftime`. El `except` por tabla se comía
    # el error como un `.skip`, así que este Parquet no se escribía nunca y en
    # silencio. `fecha_publicacion` es texto ISO, de modo que cortar los 7
    # primeros caracteres da el mes en los dos motores sin castear.
    "mat_licitaciones_por_mes": (
        "SELECT substr(fecha_publicacion, 1, 7) AS mes, "
        "COUNT(*) AS n, SUM(importe) AS importe_total, AVG(importe) AS importe_medio "
        "FROM licitaciones WHERE fecha_publicacion IS NOT NULL "
        "AND COALESCE(analysis_universe, 'technology_observed') = 'technology_observed' "
        "GROUP BY mes ORDER BY mes"
    ),
    "mat_licitaciones_por_ccaa": (
        "SELECT ccaa, COUNT(*) AS n, SUM(importe) AS importe_total "
        "FROM licitaciones WHERE ccaa IS NOT NULL "
        "AND COALESCE(analysis_universe, 'technology_observed') = 'technology_observed' "
        "GROUP BY ccaa ORDER BY n DESC"
    ),
    "mat_licitaciones_por_estado": (
        "SELECT estado, COUNT(*) AS n FROM licitaciones "
        "WHERE estado IS NOT NULL "
        "AND COALESCE(analysis_universe, 'technology_observed') = 'technology_observed' "
        "GROUP BY estado ORDER BY n DESC"
    ),
    "mat_top_adjudicatarios": (
        "SELECT a.nombre, COUNT(*) AS n, SUM(a.importe_adjudicado) AS importe_total "
        "FROM adjudicaciones a JOIN licitaciones l ON l.id_externo = a.licitacion_id "
        "WHERE a.nombre IS NOT NULL AND a.importe_adjudicado IS NOT NULL "
        "AND COALESCE(l.analysis_universe, 'technology_observed') = 'technology_observed' "
        "GROUP BY a.nombre ORDER BY importe_total DESC LIMIT 50"
    ),
    "mat_licitaciones_por_tipo": (
        "SELECT tipo_contrato, COUNT(*) AS n, SUM(importe) AS importe_total "
        "FROM licitaciones WHERE tipo_contrato IS NOT NULL "
        "AND COALESCE(analysis_universe, 'technology_observed') = 'technology_observed' "
        "GROUP BY tipo_contrato ORDER BY n DESC"
    ),
}


def run_kpi_export_parquet(output_dir: str = "data/parquet") -> dict[str, Any]:
    """Exporta agregados materializados a Parquet usando DuckDB + SQLite (F2).

    Requiere la dependencia opcional DuckDB (``pip install duckdb``).
    Si DuckDB no está disponible, intenta exportar vía pandas como fallback.

    Args:
        output_dir: Directorio de destino para los ficheros ``.parquet``.

    Returns:
        Dict con ``exported`` (lista de paths) y ``elapsed_ms``.
    """
    import time

    t0 = time.monotonic()

    try:
        from db.analytics import duckdb_query, has_duckdb

        if not has_duckdb():
            return _export_parquet_pandas_fallback(output_dir)

        from pathlib import Path

        Path(output_dir).mkdir(parents=True, exist_ok=True)
        exported: list[str] = []
        for table_name, sql in _MAT_QUERIES.items():
            dest = str(Path(output_dir) / f"{table_name}.parquet")
            copy_sql = f"COPY ({sql}) TO '{dest}' (FORMAT PARQUET)"
            try:
                duckdb_query(copy_sql)
                exported.append(dest)
                log.info("kpi_export_parquet.ok", table=table_name, dest=dest)
            except Exception as exc:
                log.warning("kpi_export_parquet.skip", table=table_name, error=str(exc))

    except Exception as exc:
        log.warning("kpi_export_parquet.fallback", error=str(exc))
        return _export_parquet_pandas_fallback(output_dir)

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    log.info("kpi_export_parquet.done", n=len(exported), elapsed_ms=elapsed_ms)
    return {"exported": exported, "elapsed_ms": elapsed_ms}


def _export_parquet_pandas_fallback(output_dir: str) -> dict[str, Any]:
    """Fallback Pandas cuando DuckDB no está disponible."""
    import time
    from pathlib import Path

    import pandas as pd

    from db.database import connect

    t0 = time.monotonic()
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    exported: list[str] = []

    with connect() as conn:
        for table_name, sql in _MAT_QUERIES.items():
            dest = str(Path(output_dir) / f"{table_name}.parquet")
            try:
                # sqlite3.Connection compatible con pandas.read_sql

                raw_conn = getattr(conn, "_conn", None) or getattr(conn, "connection", None)
                if raw_conn is None:
                    continue
                df = pd.read_sql(sql, raw_conn)
                df.to_parquet(dest, index=False, engine="pyarrow")
                exported.append(dest)
                log.info("kpi_export_parquet_pandas.ok", table=table_name, dest=dest)
            except Exception as exc:
                log.warning("kpi_export_parquet_pandas.skip", table=table_name, error=str(exc))

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    return {"exported": exported, "elapsed_ms": elapsed_ms, "engine": "pandas"}


def get_latest_snapshot(metrica: str, dimension: str = "global") -> dict[str, Any] | None:
    """Lee el snapshot más reciente de una métrica desde la BD.

    Args:
        metrica: Nombre de la métrica (e.g. "total_licitaciones").
        dimension: Dimensión (default "global").

    Returns:
        Dict con {valor, valor_text, computed_at} o None si no hay datos.
    """
    from db.database import connect

    with connect() as c:
        row = c.execute(
            "SELECT valor, valor_text, computed_at FROM kpi_snapshots "
            "WHERE metrica = %s AND dimension = %s "
            "ORDER BY computed_at DESC LIMIT 1",
            [metrica, dimension],
        ).fetchone()
    if row is None:
        return None
    result: dict[str, Any] = {"valor": row[0], "computed_at": row[2]}
    if row[1]:
        try:
            result["valor_text"] = json.loads(row[1])
        except json.JSONDecodeError:
            result["valor_text"] = row[1]
    return result


def get_all_latest() -> dict[str, Any]:
    """Devuelve todos los snapshots más recientes como un dict plano.

    Útil para cargar todos los KPIs pre-calculados de una vez.
    """
    from db.database import connect

    with connect() as c:
        # Obtener la fecha del snapshot más reciente
        row = c.execute("SELECT MAX(computed_at) FROM kpi_snapshots").fetchone()
        if not row or not row[0]:
            return {}
        latest_ts = row[0]

        rows = c.execute(
            "SELECT metrica, dimension, valor, valor_text FROM kpi_snapshots WHERE computed_at = %s",
            [latest_ts],
        ).fetchall()

    result: dict[str, Any] = {"_computed_at": latest_ts}
    for metrica, dimension, valor, valor_text in rows:
        key = metrica if dimension == "global" else f"{metrica}__{dimension}"
        if valor_text:
            try:
                result[key] = json.loads(valor_text)
            except json.JSONDecodeError:
                result[key] = valor_text
        else:
            result[key] = valor
    return result


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        log.info("kpi_precompute.starting")
        result = run_kpi_precompute()
        log.info(
            "kpi_precompute.done",
            n_metricas=result["n_metricas"],
            elapsed_ms=result["elapsed_ms"],
        )
    elif cmd == "--latest":
        from db.database import init_db

        init_db()
        data = get_all_latest()
        if not data:
            log.warning("kpi_precompute.no_snapshots")
        else:
            log.info("kpi_precompute.latest_snapshot", computed_at=data.get("_computed_at"))
            for k, v in data.items():
                if k != "_computed_at":
                    log.info("kpi_precompute.metric", key=k, value=v)
    elif cmd == "--export-parquet":
        out = sys.argv[2] if len(sys.argv) > 2 else "data/parquet"
        log.info("kpi_precompute.export_parquet.starting", output_dir=out)
        result = run_kpi_export_parquet(output_dir=out)
        exported = result.get("exported", [])
        log.info(
            "kpi_precompute.export_parquet.done",
            n_files=len(exported),
            elapsed_ms=result["elapsed_ms"],
        )
        for p in exported:
            log.info("kpi_precompute.export_parquet.file", path=p)
    else:
        log.error(
            "kpi_precompute.unknown_command",
            cmd=cmd,
            usage="python -m scheduler.kpi_precompute [run|--latest|--export-parquet [dir]]",
        )
        sys.exit(1)
