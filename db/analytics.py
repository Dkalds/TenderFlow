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

import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast

import pandas as pd

from config import settings
from observability.logging import get_logger

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


def close() -> None:
    """Cierra la conexión singleton. Útil en tests/teardown."""
    global _conn
    with _lock:
        if _conn is not None:
            try:
                _conn.close()
            except Exception:
                pass
            _conn = None
