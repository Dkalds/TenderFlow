"""Motor analítico DuckDB — singleton en memoria para hot paths del dashboard.

Proporciona un DuckDB en memoria con la tabla ``licitaciones`` adjuntada desde
SQLite. Se invalida automáticamente cuando ``shared.cache_signal`` detecta
datos nuevos del scraper.

Uso:
    from services.analytics_engine import get_engine, engine_available

    if engine_available():
        engine = get_engine()
        df = engine.execute("SELECT ccaa, COUNT(*) FROM lic GROUP BY ccaa").df()

Requiere el extra ``[fast]``: ``pip install licitaciones-sap[fast]``
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from observability.histograms import timed_query
from observability.logging import get_logger

if TYPE_CHECKING:
    import duckdb

log = get_logger(__name__)

# Nombre de la feature flag que activa el motor (configurable desde admin UI)
_FLAG_NAME = "analytics_engine_duckdb"


def engine_available() -> bool:
    """True si duckdb está instalado y la feature flag está activa."""
    try:
        import duckdb as _  # noqa: F401

        from db.feature_flags import is_enabled

        return is_enabled(_FLAG_NAME)
    except Exception:
        return False


class _DuckDBEngine:
    """Wrapper del singleton DuckDB con estado de invalidación."""

    def __init__(self, db_path: str) -> None:
        import duckdb

        self._con: duckdb.DuckDBPyConnection = duckdb.connect(":memory:")
        self._con.execute("PRAGMA memory_limit='1GB'")
        self._con.execute("PRAGMA threads=4")
        self._db_path = db_path
        self._attached_at: float = 0.0
        self._refresh()

    def _refresh(self) -> None:
        """Recarga la tabla desde SQLite."""
        try:
            with timed_query("duckdb_refresh"):
                # Detach si ya estaba adjunta
                try:
                    self._con.execute("DETACH src")
                except Exception:
                    pass
                self._con.execute(f"ATTACH '{self._db_path}' AS src (TYPE sqlite, READ_ONLY)")
                self._con.execute(
                    "CREATE OR REPLACE TABLE lic AS "
                    "SELECT id_externo, titulo, organo_contratacion, importe, estado, "
                    "       fecha_publicacion, ccaa, nuts_code, cpv, url, tecnologia, "
                    "       tipo_contrato, moneda, provincia, duracion_valor, duracion_unidad "
                    "FROM src.licitaciones "
                    "WHERE tecnologia IS NOT NULL AND tecnologia != ''"
                )
                self._attached_at = time.time()
                count = self._con.execute("SELECT COUNT(*) FROM lic").fetchone()
                log.info(
                    "duckdb_engine_refreshed",
                    rows=count[0] if count else 0,
                    db_path=self._db_path,
                )
        except Exception as exc:
            log.warning("duckdb_engine_refresh_failed", error=str(exc))

    def maybe_refresh(self) -> None:
        """Invalida y recarga si el manifest Parquet es más reciente que el último attach.

        Lee ``generated_at`` de ``DATA_DIR/parquet/_manifest.json`` (RFC 086). Si
        el manifest no existe o no se puede leer, no refresca — mantiene el
        comportamiento previo a la introducción del manifest (no rompe si el
        export Parquet nunca corrió).
        """
        try:
            from config import settings
            from shared.parquet_manifest import read_manifest

            manifest_path = settings.DATA_DIR / "parquet" / "_manifest.json"
            manifest = read_manifest(manifest_path)
            if manifest is None:
                return
            generated_ts = manifest.generated_at_timestamp()
            if generated_ts > self._attached_at:
                log.debug("duckdb_engine_invalidated_by_manifest")
                self._refresh()
        except Exception:
            pass

    def execute(self, sql: str, params: list[Any] | None = None) -> duckdb.DuckDBPyRelation:
        """Ejecuta una query y devuelve la relación DuckDB (llama .df() para DataFrame)."""
        self.maybe_refresh()
        if params:
            return self._con.execute(sql, params)
        return self._con.execute(sql)


def _build_engine() -> _DuckDBEngine | None:
    """Construye el singleton — llamado una sola vez por @st.cache_resource."""
    try:
        from config import settings

        db_path = settings.DB_PATH
        if db_path is None or not db_path.exists():
            log.warning("duckdb_engine_no_db_path", path=str(db_path))
            return None
        return _DuckDBEngine(str(db_path))
    except Exception as exc:
        log.warning("duckdb_engine_init_failed", error=str(exc))
        return None


def get_engine() -> _DuckDBEngine | None:
    """Devuelve el singleton DuckDB, cacheado por Streamlit.

    Importa streamlit sólo si disponible (no falla en scripts/tests).
    """
    try:
        import streamlit as st

        @st.cache_resource
        def _cached_engine() -> _DuckDBEngine | None:
            return _build_engine()

        return _cached_engine()
    except Exception:
        # Fuera de contexto Streamlit (tests, scripts)
        return _build_engine()
