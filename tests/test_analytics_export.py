"""Tests para db/analytics.py::run_analytics_export — snapshot Parquet + manifest (RFC 086)."""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch

from shared.parquet_manifest import read_manifest

# ── helpers ──────────────────────────────────────────────────────────────────


def _make_sqlite_db(path, *, n_licitaciones: int = 3, n_adjudicaciones: int = 2):
    """Crea un SQLite mínimo con las tablas licitaciones/adjudicaciones."""
    con = sqlite3.connect(str(path))
    try:
        con.execute("CREATE TABLE licitaciones (id INTEGER PRIMARY KEY, titulo TEXT)")
        con.execute("CREATE TABLE adjudicaciones (id INTEGER PRIMARY KEY, importe REAL)")
        con.executemany(
            "INSERT INTO licitaciones (titulo) VALUES (?)",
            [(f"lic-{i}",) for i in range(n_licitaciones)],
        )
        con.executemany(
            "INSERT INTO adjudicaciones (importe) VALUES (?)",
            [(float(i),) for i in range(n_adjudicaciones)],
        )
        con.commit()
    finally:
        con.close()


# ── run_analytics_export con DuckDB disponible ─────────────────────────────


def test_run_analytics_export_with_duckdb_writes_manifest_duckdb_engine(tmp_path):
    """Con has_duckdb()==True, exporta cada tabla a Parquet y escribe manifest engine=duckdb-parquet."""
    import db.analytics as analytics

    sqlite_file = tmp_path / "licitaciones.db"
    _make_sqlite_db(sqlite_file, n_licitaciones=5, n_adjudicaciones=7)

    output_dir = tmp_path / "parquet"

    fake_df_lic = MagicMock()
    fake_df_lic.empty = False
    fake_df_lic.__getitem__.return_value.iloc.__getitem__.return_value = 5

    fake_df_adj = MagicMock()
    fake_df_adj.empty = False
    fake_df_adj.__getitem__.return_value.iloc.__getitem__.return_value = 7

    export_calls = []
    query_calls = []

    def _fake_export_parquet(sql, out_path, *, compression="zstd"):
        export_calls.append((sql, str(out_path)))
        return out_path

    def _fake_duckdb_query(sql, params=None):
        query_calls.append(sql)
        if "licitaciones" in sql:
            return fake_df_lic
        return fake_df_adj

    with (
        patch.object(analytics, "_sqlite_path", return_value=sqlite_file),
        patch.object(analytics, "has_duckdb", return_value=True),
        patch.object(analytics, "export_parquet", side_effect=_fake_export_parquet),
        patch.object(analytics, "duckdb_query", side_effect=_fake_duckdb_query),
    ):
        result = analytics.run_analytics_export(output_dir=output_dir)

    assert result["engine"] == "duckdb-parquet"
    assert result["row_counts"] == {"licitaciones": 5, "adjudicaciones": 7}

    # export_parquet llamado una vez por tabla
    assert len(export_calls) == 2
    exported_paths = {str(p) for _, p in export_calls}
    assert str(output_dir / "licitaciones.parquet") in exported_paths
    assert str(output_dir / "adjudicaciones.parquet") in exported_paths

    # Manifest escrito en disco con engine duckdb-parquet
    manifest_path = output_dir / "_manifest.json"
    assert manifest_path.exists()
    manifest = read_manifest(manifest_path)
    assert manifest is not None
    assert manifest.engine == "duckdb-parquet"
    assert manifest.row_counts == {"licitaciones": 5, "adjudicaciones": 7}


# ── run_analytics_export sin DuckDB (fallback sqlite-direct) ───────────────


def test_run_analytics_export_without_duckdb_falls_back_to_sqlite_direct(tmp_path):
    """Con has_duckdb()==False, no genera .parquet y escribe manifest engine=sqlite-direct
    con row_counts leídos directamente de SQLite."""
    import db.analytics as analytics

    sqlite_file = tmp_path / "licitaciones.db"
    _make_sqlite_db(sqlite_file, n_licitaciones=3, n_adjudicaciones=4)

    output_dir = tmp_path / "parquet"

    with (
        patch.object(analytics, "_sqlite_path", return_value=sqlite_file),
        patch.object(analytics, "has_duckdb", return_value=False),
        patch.object(analytics, "export_parquet") as mock_export,
    ):
        result = analytics.run_analytics_export(output_dir=output_dir)

    assert result["engine"] == "sqlite-direct"
    assert result["row_counts"] == {"licitaciones": 3, "adjudicaciones": 4}
    mock_export.assert_not_called()

    # No se generan ficheros .parquet
    assert not (output_dir / "licitaciones.parquet").exists()
    assert not (output_dir / "adjudicaciones.parquet").exists()

    # Manifest escrito con engine sqlite-direct
    manifest_path = output_dir / "_manifest.json"
    assert manifest_path.exists()
    manifest = read_manifest(manifest_path)
    assert manifest is not None
    assert manifest.engine == "sqlite-direct"
    assert manifest.row_counts == {"licitaciones": 3, "adjudicaciones": 4}


def test_run_analytics_export_returns_summary_with_manifest_path_and_elapsed(tmp_path):
    """El resumen devuelto incluye manifest_path y elapsed_ms."""
    import db.analytics as analytics

    sqlite_file = tmp_path / "licitaciones.db"
    _make_sqlite_db(sqlite_file)

    output_dir = tmp_path / "parquet"

    with (
        patch.object(analytics, "_sqlite_path", return_value=sqlite_file),
        patch.object(analytics, "has_duckdb", return_value=False),
    ):
        result = analytics.run_analytics_export(output_dir=output_dir)

    assert result["manifest_path"] == str(output_dir / "_manifest.json")
    assert isinstance(result["elapsed_ms"], int)
    assert result["elapsed_ms"] >= 0


def test_sqlite_row_counts_reads_directly_from_sqlite(tmp_path):
    """_sqlite_row_counts devuelve los COUNT(*) reales para cada tabla."""
    import db.analytics as analytics

    sqlite_file = tmp_path / "licitaciones.db"
    _make_sqlite_db(sqlite_file, n_licitaciones=10, n_adjudicaciones=1)

    with patch.object(analytics, "_sqlite_path", return_value=sqlite_file):
        counts = analytics._sqlite_row_counts(analytics._ANALYTICS_TABLES)

    assert counts == {"licitaciones": 10, "adjudicaciones": 1}
