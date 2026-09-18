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

Dónde está el SQL
-----------------
En :mod:`db.kpi_precompute` (ADR-022): las consultas de métricas, el reemplazo
del snapshot, sus lecturas y las consultas materializadas, junto con la decisión
del 2026-09-03 sobre **qué universo miden** estos KPIs. Este módulo se queda con
la orquestación —cronometrar, elegir motor para el Parquet, escribir los
ficheros y loguear— y no abre conexiones. Los logs salen de aquí y no de ``db/``
para que sigan firmados por el logger ``scheduler.kpi_precompute``.

El job llega al SQL como ``kpi_db.<nombre>``, un atributo de
:mod:`db.kpi_precompute` que se resuelve en cada llamada. Para sustituir una
consulta en un test se parchea ahí o ``db.database.connect``: en este módulo no
queda ningún alias del SQL por el que pase el job.
"""

from __future__ import annotations

from typing import Any

from db import kpi_precompute as kpi_db
from observability.logging import get_logger

log = get_logger(__name__)

# Reexportación, no costura: ni `run_kpi_precompute` ni el `--latest` de abajo
# pasan por este nombre, así que parchearlo aquí no cambia lo que hace el job.
# Existe solo porque `tests/test_integration_e2e.py` lo importa desde este
# módulo; cuando lo importe de `db.kpi_precompute`, sobra.
get_all_latest = kpi_db.get_all_latest


def run_kpi_precompute() -> dict[str, Any]:
    """Ejecuta el pre-cálculo completo de KPIs y los persiste en la BD.

    Returns:
        Resumen con n_metricas calculadas y tiempo de ejecución.
    """
    import time

    from db.database import init_db

    t0 = time.monotonic()
    init_db()

    n = kpi_db.compute_and_persist_snapshots()

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    log.info("kpi_precompute.done", n_metricas=n, elapsed_ms=elapsed_ms)
    return {"n_metricas": n, "elapsed_ms": elapsed_ms}


# ── Exportación Parquet materializada (F2) ────────────────────────────────────


def run_kpi_export_parquet(output_dir: str = "data/parquet") -> dict[str, Any]:
    """Exporta agregados materializados a Parquet usando DuckDB sobre Postgres (F2).

    Requiere la dependencia opcional DuckDB (``pip install duckdb``), que
    :mod:`db.analytics` adjunta a Postgres en modo lectura. Si DuckDB no está
    disponible, o falla antes de empezar a exportar, lo intenta vía pandas.

    Args:
        output_dir: Directorio de destino para los ficheros ``.parquet``.

    Returns:
        Dict con ``exported`` (lista de paths) y ``elapsed_ms``.
    """
    import time

    t0 = time.monotonic()

    try:
        from db.analytics import has_duckdb

        if not has_duckdb():
            return _export_parquet_pandas_fallback(output_dir)

        from pathlib import Path

        Path(output_dir).mkdir(parents=True, exist_ok=True)
        exported: list[str] = []
        for table_name in kpi_db.MAT_QUERIES:
            dest = str(Path(output_dir) / f"{table_name}.parquet")
            try:
                kpi_db.export_mat_query_duckdb(table_name, dest)
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

    t0 = time.monotonic()
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    exported: list[str] = []

    with kpi_db.mat_query_reader() as leer:
        for table_name in kpi_db.MAT_QUERIES:
            dest = str(Path(output_dir) / f"{table_name}.parquet")
            try:
                if leer is None:
                    continue
                df: pd.DataFrame = leer(table_name)
                df.to_parquet(dest, index=False, engine="pyarrow")
                exported.append(dest)
                log.info("kpi_export_parquet_pandas.ok", table=table_name, dest=dest)
            except Exception as exc:
                log.warning("kpi_export_parquet_pandas.skip", table=table_name, error=str(exc))

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    return {"exported": exported, "elapsed_ms": elapsed_ms, "engine": "pandas"}


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
        data = kpi_db.get_all_latest()
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
