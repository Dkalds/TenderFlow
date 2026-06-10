"""Motor analítico opcional basado en DuckDB.

DuckDB se ATTACHa sobre el fichero SQLite de producción en modo lectura
para ejecutar queries OLAP pesadas (group-by sobre millones de filas,
window functions, joins múltiples) órdenes de magnitud más rápido que
SQLite mientras la BD operacional sigue siendo SQLite/Turso.

Diseño (F2):
    * La conexión DuckDB es **opcional** — si DuckDB no está instalado, las
      funciones devuelven ``None`` y los callers caen al backend SQLite.
    * Modo lectura siempre: ``read_only=True`` para garantizar que las
      analíticas no pueden corromper la BD operacional.
    * Persistencia opcional a Parquet para snapshots históricos
      (KPI precompute, materializaciones por mes/CCAA).

Instalación: ``pip install duckdb`` (no es dependencia core).

Uso típico::

    from db.analytics import duckdb_query, has_duckdb

    if has_duckdb():
        df = duckdb_query(
            "SELECT ccaa, COUNT(*) AS n FROM sqlite_db.licitaciones "
            "WHERE fecha_publicacion >= '2024-01-01' GROUP BY ccaa"
        )
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast

import pandas as pd

from config import settings
from observability.logging import get_logger
from shared.parquet_manifest import ManifestEngine, write_manifest

log = get_logger(__name__)

try:  # pragma: no cover - dependencia opcional
    import duckdb

    _DUCKDB_AVAILABLE = True
except ImportError:  # pragma: no cover
    duckdb = None
    _DUCKDB_AVAILABLE = False


_SQLITE_ALIAS = "sqlite_db"
_lock = threading.Lock()
_conn: Any = None


def has_duckdb() -> bool:
    """True si DuckDB está disponible en runtime."""
    return _DUCKDB_AVAILABLE


def _sqlite_path() -> Path:
    """Resuelve la ruta del fichero SQLite de producción."""
    candidates: list[Path | str | None] = [
        getattr(settings, "DATABASE_PATH", None),
        getattr(settings, "SQLITE_PATH", None),
        getattr(settings, "DATA_DIR", None),
    ]
    for c in candidates:
        if not c:
            continue
        p = Path(str(c))
        if p.is_file():
            return p
        guess = p / "licitaciones.db"
        if guess.is_file():
            return guess
    raise FileNotFoundError("No se encontró el fichero SQLite operacional.")


def get_connection() -> Any:
    """Devuelve una conexión DuckDB singleton con el SQLite operacional adjunto.

    Lanza ``RuntimeError`` si DuckDB no está instalado. La conexión es
    thread-safe gracias al lock interno; las consultas son lecturas.
    """
    if not _DUCKDB_AVAILABLE:
        raise RuntimeError("DuckDB no está instalado. Instalar con: pip install duckdb")
    global _conn
    with _lock:
        if _conn is None:
            sqlite_file = _sqlite_path()
            con = duckdb.connect(database=":memory:")
            con.execute("INSTALL sqlite_scanner;")
            con.execute("LOAD sqlite_scanner;")
            # El parámetro read_only previene escrituras hacia el fichero SQLite.
            con.execute(f"ATTACH '{sqlite_file}' AS {_SQLITE_ALIAS} (TYPE SQLITE, READ_ONLY);")
            _conn = con
            log.info("duckdb_attached", sqlite=str(sqlite_file))
        return _conn


def duckdb_query(sql: str, params: Iterable[Any] | None = None) -> pd.DataFrame | None:
    """Ejecuta una query DuckDB y devuelve un DataFrame.

    Devuelve ``None`` si DuckDB no está disponible — el caller debe
    implementar fallback a SQLite.
    """
    if not _DUCKDB_AVAILABLE:
        return None
    con = get_connection()
    with _lock:
        cur = con.execute(sql, list(params) if params else None)
        return cast(pd.DataFrame, cur.fetch_df())


def export_parquet(sql: str, out_path: Path | str, *, compression: str = "zstd") -> Path:
    """Materializa una query DuckDB a Parquet (para `scheduler/kpi_precompute`).

    Lanza ``RuntimeError`` si DuckDB no está disponible.
    """
    if not _DUCKDB_AVAILABLE:
        raise RuntimeError("DuckDB no está instalado; export_parquet requiere duckdb.")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    con = get_connection()
    with _lock:
        con.execute(
            f"COPY ({sql}) TO '{out.as_posix()}' (FORMAT PARQUET, COMPRESSION '{compression}');"
        )
    log.info("duckdb_export_parquet", path=str(out), compression=compression)
    return out


#: Tablas de hechos analíticos exportadas al snapshot Parquet (RFC 086).
_ANALYTICS_TABLES: tuple[str, ...] = ("licitaciones", "adjudicaciones")


def _sqlite_row_counts(tables: Iterable[str]) -> dict[str, int]:
    """Lee ``SELECT COUNT(*)`` de cada tabla directamente desde SQLite."""
    counts: dict[str, int] = {}
    sqlite_file = _sqlite_path()
    con = sqlite3.connect(f"file:{sqlite_file.as_posix()}?mode=ro", uri=True)
    try:
        for table in tables:
            cur = con.execute(f"SELECT COUNT(*) FROM {table}")
            row = cur.fetchone()
            counts[table] = int(row[0]) if row else 0
    finally:
        con.close()
    return counts


def run_analytics_export(output_dir: Path | str | None = None) -> dict[str, Any]:
    """Exporta el snapshot Parquet de hechos analíticos y escribe el manifest (RFC 086).

    Si DuckDB está disponible (:func:`has_duckdb`), exporta ``licitaciones`` y
    ``adjudicaciones`` completas a ``<output_dir>/licitaciones.parquet`` y
    ``<output_dir>/adjudicaciones.parquet`` (compresión zstd, re-export full).
    En caso contrario, no falla: escribe igualmente el manifest con
    ``engine="sqlite-direct"`` y ``row_counts`` leídos directamente de SQLite,
    sin generar ficheros ``.parquet``.

    En ambos casos termina escribiendo ``<output_dir>/_manifest.json`` vía
    :func:`shared.parquet_manifest.write_manifest`.

    Args:
        output_dir: Directorio destino. Por defecto ``DATA_DIR/parquet``.

    Returns:
        Resumen con ``engine``, ``row_counts``, ``manifest_path`` y ``elapsed_ms``.
    """
    t0 = time.monotonic()
    out_dir = Path(output_dir) if output_dir is not None else Path(settings.DATA_DIR) / "parquet"
    out_dir.mkdir(parents=True, exist_ok=True)

    sqlite_file = _sqlite_path()
    source_db_mtime = sqlite_file.stat().st_mtime

    engine: ManifestEngine
    row_counts: dict[str, int]
    if has_duckdb():
        engine = "duckdb-parquet"
        row_counts = {}
        for table in _ANALYTICS_TABLES:
            dest = out_dir / f"{table}.parquet"
            export_parquet(
                f"SELECT * FROM {_SQLITE_ALIAS}.{table}",
                dest,
                compression="zstd",
            )
            df_count = duckdb_query(f"SELECT COUNT(*) AS n FROM {_SQLITE_ALIAS}.{table}")
            row_counts[table] = (
                int(df_count["n"].iloc[0]) if df_count is not None and not df_count.empty else 0
            )
    else:
        engine = "sqlite-direct"
        row_counts = _sqlite_row_counts(_ANALYTICS_TABLES)

    manifest_path = out_dir / "_manifest.json"
    write_manifest(
        manifest_path,
        engine=engine,
        row_counts=row_counts,
        source_db_mtime=source_db_mtime,
    )

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    log.info(
        "analytics_export_done",
        engine=engine,
        row_counts=row_counts,
        manifest_path=str(manifest_path),
        elapsed_ms=elapsed_ms,
    )
    return {
        "engine": engine,
        "row_counts": row_counts,
        "manifest_path": str(manifest_path),
        "elapsed_ms": elapsed_ms,
    }


def close() -> None:
    """Cierra la conexión singleton. Útil en tests/teardown."""
    global _conn
    with _lock:
        if _conn is not None:
            try:
                _conn.close()
            except Exception:
                log.debug("duckdb_close_failed", exc_info=True)
            _conn = None
