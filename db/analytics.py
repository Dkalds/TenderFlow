"""Motor analítico opcional basado en DuckDB.

DuckDB se ATTACHa sobre la BD operacional Postgres en modo lectura (extensión
``postgres_scanner``) para ejecutar queries OLAP pesadas (group-by sobre
millones de filas, window functions, joins múltiples) órdenes de magnitud más
rápido que el motor transaccional.

Hasta ADR-021 este módulo adjuntaba un fichero SQLite con ``sqlite_scanner``.
Retirado SQLite, ese camino quedó muerto —``_sqlite_path()`` lanzaba
``FileNotFoundError`` en cada llamada— y con él los exports OLAP a Parquet que
consume ``scheduler/pipeline_runs.py``. Ahora el ATTACH es
``(TYPE POSTGRES, READ_ONLY)`` contra ``DATABASE_URL``.

Diseño (F2):
    * La conexión DuckDB es **opcional** — si DuckDB no está instalado, las
      funciones devuelven ``None`` y el export cae al camino directo por
      Postgres (solo row counts, sin ficheros Parquet).
    * Modo lectura siempre: ``READ_ONLY`` garantiza que las analíticas no
      pueden escribir sobre la BD operacional.
    * Persistencia opcional a Parquet para snapshots históricos
      (KPI precompute, materializaciones por mes/CCAA).

Instalación: ``pip install duckdb`` (no es dependencia core).

Uso típico::

    from db.analytics import duckdb_query, has_duckdb

    if has_duckdb():
        df = duckdb_query(
            "SELECT ccaa, COUNT(*) AS n FROM pg_db.licitaciones "
            "WHERE fecha_publicacion >= '2024-01-01' GROUP BY ccaa"
        )
"""

from __future__ import annotations

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


#: Alias del catálogo Postgres dentro de DuckDB. Las queries lo referencian como
#: ``pg_db.<tabla>``.
_PG_ALIAS = "pg_db"
_lock = threading.Lock()
_conn: Any = None


def has_duckdb() -> bool:
    """True si DuckDB está disponible en runtime."""
    return _DUCKDB_AVAILABLE


def _database_url() -> str:
    """DSN de la BD operacional, o lanza si no está configurada."""
    raw = settings.DATABASE_URL.get_secret_value() if settings.DATABASE_URL else ""
    if not raw:
        raise RuntimeError(
            "DATABASE_URL no está configurada: el motor analítico DuckDB "
            "adjunta la BD Postgres operacional y no tiene otra fuente."
        )
    return raw


def get_connection() -> Any:
    """Devuelve una conexión DuckDB singleton con la BD Postgres adjunta.

    Lanza ``RuntimeError`` si DuckDB no está instalado o si ``DATABASE_URL`` no
    está configurada. La conexión es thread-safe gracias al lock interno; las
    consultas son lecturas.
    """
    if not _DUCKDB_AVAILABLE:
        raise RuntimeError("DuckDB no está instalado. Instalar con: pip install duckdb")
    global _conn
    with _lock:
        if _conn is None:
            dsn = _database_url()
            con = duckdb.connect(database=":memory:")
            con.execute("INSTALL postgres;")
            con.execute("LOAD postgres;")
            # READ_ONLY previene escrituras hacia la BD operacional. El DSN se
            # interpola pero nunca se loguea: lleva la contraseña.
            con.execute(f"ATTACH '{dsn}' AS {_PG_ALIAS} (TYPE POSTGRES, READ_ONLY);")
            _conn = con
            log.info("duckdb_attached", backend="postgres")
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


def _source_db_mtime() -> float:
    """Marca de frescura de la BD origen, en epoch.

    Con SQLite era el ``mtime`` del fichero. Postgres no expone nada
    equivalente por tabla, así que se usa ``MAX(fecha_extraccion)`` de
    ``licitaciones`` — la misma señal que sirve el header ``Last-Modified`` de
    la API (``api/routes/meta.py``), y la que de verdad responde a la pregunta
    del manifest: *¿el snapshot quedó desactualizado respecto al dato?*

    Devuelve ``0.0`` si la tabla está vacía o la fecha no es parseable: el
    manifest se escribe igual y el lector interpreta 0 como "sin señal".
    """
    from datetime import datetime

    from db.repositories.licitaciones import LicitacionRepository

    raw = LicitacionRepository().get_last_extraction_date()
    if not raw:
        return 0.0
    try:
        return datetime.fromisoformat(str(raw)).timestamp()
    except ValueError:
        log.warning("analytics_source_mtime_unparseable", value=str(raw))
        return 0.0


def _postgres_row_counts(tables: Iterable[str]) -> dict[str, int]:
    """Lee ``SELECT COUNT(*)`` de cada tabla directamente desde Postgres.

    Camino de respaldo cuando DuckDB no está instalado: el manifest sigue
    registrando frescura y volumen aunque no se generen ficheros Parquet.
    """
    from db.database import connect_read

    counts: dict[str, int] = {}
    with connect_read() as c:
        for table in tables:
            # `table` sale de la constante _ANALYTICS_TABLES, no de entrada externa.
            row = c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            counts[table] = int(row[0]) if row else 0
    return counts


def run_analytics_export(output_dir: Path | str | None = None) -> dict[str, Any]:
    """Exporta el snapshot Parquet de hechos analíticos y escribe el manifest (RFC 086).

    Si DuckDB está disponible (:func:`has_duckdb`), exporta ``licitaciones`` y
    ``adjudicaciones`` completas a ``<output_dir>/licitaciones.parquet`` y
    ``<output_dir>/adjudicaciones.parquet`` (compresión zstd, re-export full).
    En caso contrario, no falla: escribe igualmente el manifest con
    ``engine="postgres-direct"`` y ``row_counts`` leídos directamente de
    Postgres, sin generar ficheros ``.parquet``.

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

    source_db_mtime = _source_db_mtime()

    engine: ManifestEngine
    row_counts: dict[str, int]
    if has_duckdb():
        engine = "duckdb-parquet"
        row_counts = {}
        for table in _ANALYTICS_TABLES:
            dest = out_dir / f"{table}.parquet"
            export_parquet(
                f"SELECT * FROM {_PG_ALIAS}.{table}",
                dest,
                compression="zstd",
            )
            df_count = duckdb_query(f"SELECT COUNT(*) AS n FROM {_PG_ALIAS}.{table}")
            row_counts[table] = (
                int(df_count["n"].iloc[0]) if df_count is not None and not df_count.empty else 0
            )
    else:
        engine = "postgres-direct"
        row_counts = _postgres_row_counts(_ANALYTICS_TABLES)

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
