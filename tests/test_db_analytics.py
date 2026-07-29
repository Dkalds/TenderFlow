"""Tests para db/analytics.py — puente DuckDB/SQLite para consultas analíticas."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


class TestAnalyticsSqlitePath:
    def test_finds_file_from_DATABASE_PATH(self, tmp_path):
        from db import analytics

        db_file = tmp_path / "test.db"
        db_file.touch()
        with patch.object(analytics, "settings", create=True) as mock_s:
            mock_s.DATABASE_PATH = str(db_file)
            mock_s.SQLITE_PATH = None
            mock_s.DATA_DIR = None
            result = analytics._sqlite_path()
            assert result == db_file

    def test_finds_file_from_DATA_DIR(self, tmp_path):
        from db import analytics

        db_file = tmp_path / "licitaciones.db"
        db_file.touch()
        with patch.object(analytics, "settings", create=True) as mock_s:
            mock_s.DATABASE_PATH = None
            mock_s.SQLITE_PATH = None
            mock_s.DATA_DIR = str(tmp_path)
            result = analytics._sqlite_path()
            assert result == db_file

    def test_raises_when_not_found(self):
        from db import analytics

        with patch.object(analytics, "settings", create=True) as mock_s:
            mock_s.DATABASE_PATH = None
            mock_s.SQLITE_PATH = None
            mock_s.DATA_DIR = None
            with pytest.raises(FileNotFoundError):
                analytics._sqlite_path()


class TestHasDuckdb:
    def test_returns_bool(self):
        from db.analytics import has_duckdb

        assert isinstance(has_duckdb(), bool)


class TestDuckdbQueryNoDuckdb:
    def test_returns_none_when_unavailable(self):
        from db import analytics

        original = analytics._DUCKDB_AVAILABLE
        try:
            analytics._DUCKDB_AVAILABLE = False
            result = analytics.duckdb_query("SELECT 1")
            assert result is None
        finally:
            analytics._DUCKDB_AVAILABLE = original


class TestGetConnectionNoDuckdb:
    def test_raises_when_unavailable(self):
        from db import analytics

        original = analytics._DUCKDB_AVAILABLE
        try:
            analytics._DUCKDB_AVAILABLE = False
            with pytest.raises(RuntimeError, match="DuckDB no está instalado"):
                analytics.get_connection()
        finally:
            analytics._DUCKDB_AVAILABLE = original


class TestExportParquetNoDuckdb:
    def test_raises_when_unavailable(self):
        from db import analytics

        original = analytics._DUCKDB_AVAILABLE
        try:
            analytics._DUCKDB_AVAILABLE = False
            with pytest.raises(RuntimeError):
                analytics.export_parquet("SELECT 1", "test_output.parquet")
        finally:
            analytics._DUCKDB_AVAILABLE = original


class TestGetConnectionWithDuckdb:
    def test_creates_connection(self):
        from db import analytics

        original_avail = analytics._DUCKDB_AVAILABLE
        original_conn = analytics._conn
        try:
            analytics._DUCKDB_AVAILABLE = True
            analytics._conn = None

            mock_con = MagicMock()
            mock_duckdb = MagicMock()
            mock_duckdb.connect.return_value = mock_con

            with (
                patch.object(analytics, "duckdb", mock_duckdb),
                patch.object(analytics, "_sqlite_path", return_value=Path("/fake/db.sqlite")),
            ):
                conn = analytics.get_connection()
                assert conn is mock_con
                mock_con.execute.assert_any_call("INSTALL sqlite_scanner;")
        finally:
            analytics._DUCKDB_AVAILABLE = original_avail
            analytics._conn = original_conn


class TestDuckdbQueryWithDuckdb:
    def test_executes_query(self):
        from db import analytics

        original_avail = analytics._DUCKDB_AVAILABLE
        original_conn = analytics._conn
        try:
            analytics._DUCKDB_AVAILABLE = True
            mock_con = MagicMock()
            mock_df = pd.DataFrame({"a": [1]})
            mock_con.execute.return_value.fetch_df.return_value = mock_df
            analytics._conn = mock_con

            result = analytics.duckdb_query("SELECT 1", [42])
            assert result is not None
            mock_con.execute.assert_called_with("SELECT 1", [42])
        finally:
            analytics._DUCKDB_AVAILABLE = original_avail
            analytics._conn = original_conn

    def test_executes_query_no_params(self):
        from db import analytics

        original_avail = analytics._DUCKDB_AVAILABLE
        original_conn = analytics._conn
        try:
            analytics._DUCKDB_AVAILABLE = True
            mock_con = MagicMock()
            mock_df = pd.DataFrame()
            mock_con.execute.return_value.fetch_df.return_value = mock_df
            analytics._conn = mock_con

            result = analytics.duckdb_query("SELECT 1")
            mock_con.execute.assert_called_with("SELECT 1", None)
        finally:
            analytics._DUCKDB_AVAILABLE = original_avail
            analytics._conn = original_conn


class TestExportParquetWithDuckdb:
    def test_exports(self, tmp_path):
        from db import analytics

        original_avail = analytics._DUCKDB_AVAILABLE
        original_conn = analytics._conn
        try:
            analytics._DUCKDB_AVAILABLE = True
            mock_con = MagicMock()
            analytics._conn = mock_con

            out = tmp_path / "out.parquet"
            result = analytics.export_parquet("SELECT 1", out, compression="snappy")
            assert result == out
            mock_con.execute.assert_called_once()
        finally:
            analytics._DUCKDB_AVAILABLE = original_avail
            analytics._conn = original_conn


class TestAnalyticsClose:
    def test_close_with_conn(self):
        from db import analytics

        original_conn = analytics._conn
        try:
            mock_con = MagicMock()
            analytics._conn = mock_con
            analytics.close()
            mock_con.close.assert_called_once()
            assert analytics._conn is None
        finally:
            analytics._conn = original_conn

    def test_close_with_no_conn(self):
        from db import analytics

        original_conn = analytics._conn
        try:
            analytics._conn = None
            analytics.close()  # should not raise
            assert analytics._conn is None
        finally:
            analytics._conn = original_conn

    def test_close_swallows_exception(self):
        from db import analytics

        original_conn = analytics._conn
        try:
            mock_con = MagicMock()
            mock_con.close.side_effect = RuntimeError("boom")
            analytics._conn = mock_con
            analytics.close()  # should not raise
            assert analytics._conn is None
        finally:
            analytics._conn = original_conn
