"""Tests para db/analytics.py::run_analytics_export — snapshot Parquet + manifest (RFC 086).

Estos tests cubrían el camino SQLite (``sqlite_scanner`` + ``_sqlite_path``),
retirado en ADR-021 y sustituido por ``postgres_scanner``. Se reescribieron
sobre el camino Postgres conservando los mismos casos: export con DuckDB,
fallback sin DuckDB, forma del resumen y lectura directa de row counts.

**Alcance honesto:** son tests de *wiring*, no de la extensión. Verifican que
el módulo ya no resuelve ficheros SQLite y que el ATTACH se construye contra
``DATABASE_URL``, pero no ejercitan ``postgres_scanner`` real —DuckDB es
dependencia opcional y la extensión se descarga en runtime—, así que un fallo
de la extensión en producción no lo cazan. Esa cobertura necesita un entorno
con DuckDB + la extensión instalada.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from shared.parquet_manifest import read_manifest

# Epoch arbitrario y estable: sustituye al mtime del fichero SQLite de antes.
_FAKE_MTIME = 1_718_000_000.0


# ── run_analytics_export con DuckDB disponible ─────────────────────────────


def test_run_analytics_export_with_duckdb_writes_manifest_duckdb_engine(tmp_path):
    """Con has_duckdb()==True, exporta cada tabla a Parquet y escribe manifest engine=duckdb-parquet."""
    import db.analytics as analytics

    output_dir = tmp_path / "parquet"

    fake_df_lic = MagicMock()
    fake_df_lic.empty = False
    fake_df_lic.__getitem__.return_value.iloc.__getitem__.return_value = 5

    fake_df_adj = MagicMock()
    fake_df_adj.empty = False
    fake_df_adj.__getitem__.return_value.iloc.__getitem__.return_value = 7

    export_calls = []

    def _fake_export_parquet(sql, out_path, *, compression="zstd"):
        export_calls.append((sql, str(out_path)))
        return out_path

    def _fake_duckdb_query(sql, params=None):
        return fake_df_lic if "licitaciones" in sql else fake_df_adj

    with (
        patch.object(analytics, "_source_db_mtime", return_value=_FAKE_MTIME),
        patch.object(analytics, "has_duckdb", return_value=True),
        patch.object(analytics, "export_parquet", side_effect=_fake_export_parquet),
        patch.object(analytics, "duckdb_query", side_effect=_fake_duckdb_query),
    ):
        result = analytics.run_analytics_export(output_dir=output_dir)

    assert result["engine"] == "duckdb-parquet"
    assert result["row_counts"] == {"licitaciones": 5, "adjudicaciones": 7}

    # export_parquet llamado una vez por tabla, contra el catálogo Postgres.
    assert len(export_calls) == 2
    exported_paths = {p for _, p in export_calls}
    assert str(output_dir / "licitaciones.parquet") in exported_paths
    assert str(output_dir / "adjudicaciones.parquet") in exported_paths
    assert all(f"{analytics._PG_ALIAS}." in sql for sql, _ in export_calls)

    manifest_path = output_dir / "_manifest.json"
    assert manifest_path.exists()
    manifest = read_manifest(manifest_path)
    assert manifest is not None
    assert manifest.engine == "duckdb-parquet"
    assert manifest.row_counts == {"licitaciones": 5, "adjudicaciones": 7}
    assert manifest.source_db_mtime == _FAKE_MTIME


# ── run_analytics_export sin DuckDB (fallback postgres-direct) ─────────────


def test_run_analytics_export_without_duckdb_falls_back_to_postgres_direct(tmp_path):
    """Con has_duckdb()==False, no genera .parquet y escribe manifest engine=postgres-direct
    con row_counts leídos directamente de Postgres."""
    import db.analytics as analytics

    output_dir = tmp_path / "parquet"

    with (
        patch.object(analytics, "_source_db_mtime", return_value=_FAKE_MTIME),
        patch.object(analytics, "has_duckdb", return_value=False),
        patch.object(
            analytics,
            "_postgres_row_counts",
            return_value={"licitaciones": 3, "adjudicaciones": 4},
        ),
        patch.object(analytics, "export_parquet") as mock_export,
    ):
        result = analytics.run_analytics_export(output_dir=output_dir)

    assert result["engine"] == "postgres-direct"
    assert result["row_counts"] == {"licitaciones": 3, "adjudicaciones": 4}
    mock_export.assert_not_called()

    assert not (output_dir / "licitaciones.parquet").exists()
    assert not (output_dir / "adjudicaciones.parquet").exists()

    manifest_path = output_dir / "_manifest.json"
    assert manifest_path.exists()
    manifest = read_manifest(manifest_path)
    assert manifest is not None
    assert manifest.engine == "postgres-direct"
    assert manifest.row_counts == {"licitaciones": 3, "adjudicaciones": 4}


def test_run_analytics_export_returns_summary_with_manifest_path_and_elapsed(tmp_path):
    """El resumen devuelto incluye manifest_path y elapsed_ms."""
    import db.analytics as analytics

    output_dir = tmp_path / "parquet"

    with (
        patch.object(analytics, "_source_db_mtime", return_value=_FAKE_MTIME),
        patch.object(analytics, "has_duckdb", return_value=False),
        patch.object(analytics, "_postgres_row_counts", return_value={}),
    ):
        result = analytics.run_analytics_export(output_dir=output_dir)

    assert result["manifest_path"] == str(output_dir / "_manifest.json")
    assert isinstance(result["elapsed_ms"], int)
    assert result["elapsed_ms"] >= 0


def test_postgres_row_counts_reads_directly_from_postgres():
    """_postgres_row_counts emite un COUNT(*) por tabla sobre la conexión de lectura."""
    import db.analytics as analytics

    cursor = MagicMock()
    cursor.fetchone.side_effect = [(10,), (1,)]
    conn = MagicMock()
    conn.execute.return_value = cursor
    ctx = MagicMock()
    ctx.__enter__.return_value = conn

    with patch("db.database.connect_read", return_value=ctx):
        counts = analytics._postgres_row_counts(analytics._ANALYTICS_TABLES)

    assert counts == {"licitaciones": 10, "adjudicaciones": 1}
    assert conn.execute.call_count == 2


# ── Regresión de ADR-021: el módulo ya no toca ficheros SQLite ─────────────


def test_module_has_no_sqlite_path_resolution():
    """El camino SQLite quedó retirado: ni resolutor de fichero ni row counts.

    Es el AC del ítem de backlog: antes ``get_connection`` llamaba a
    ``_sqlite_path()``, que lanzaba ``FileNotFoundError`` en cada invocación
    porque el fichero dejó de existir con ADR-021.
    """
    import db.analytics as analytics

    assert not hasattr(analytics, "_sqlite_path")
    assert not hasattr(analytics, "_sqlite_row_counts")
    assert not hasattr(analytics, "_SQLITE_ALIAS")


def test_get_connection_attaches_postgres_with_read_only():
    """get_connection ATTACHea DATABASE_URL como POSTGRES READ_ONLY, no SQLite."""
    import db.analytics as analytics

    fake_con = MagicMock()
    dsn = "postgresql://u:p@localhost:5432/db"  # pragma: allowlist secret -- DSN de prueba

    with (
        patch.object(analytics, "_DUCKDB_AVAILABLE", True),
        patch.object(analytics, "_conn", None),
        patch.object(analytics, "_database_url", return_value=dsn),
        patch.object(analytics, "duckdb", MagicMock(connect=MagicMock(return_value=fake_con))),
    ):
        analytics.get_connection()
        analytics._conn = None  # no contaminar el singleton para otros tests

    executed = " ".join(call.args[0] for call in fake_con.execute.call_args_list)
    assert "LOAD postgres" in executed
    assert "TYPE POSTGRES, READ_ONLY" in executed
    assert "sqlite" not in executed.lower()
