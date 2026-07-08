"""Unit tests for saved_filters, analytics, drift_monitor, and queue modules."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# ═══════════════════════════════════════════════════════════════════════════════
# db.saved_filters
# ═══════════════════════════════════════════════════════════════════════════════


class TestFiltersToJson:
    def test_basic_serialization(self):
        from db.saved_filters import filters_to_json

        fs = SimpleNamespace(
            q="test",
            estados=["A"],
            ccaas=["Madrid"],
            organos=["X"],
            tipos_proy=["T"],
            tecnologias=["Python"],
            importe_min=1000,
            rango=None,
        )
        result = json.loads(filters_to_json(fs))
        assert result["q"] == "test"
        assert result["rango"] is None

    def test_with_rango(self):
        from db.saved_filters import filters_to_json

        fs = SimpleNamespace(
            q="",
            estados=[],
            ccaas=[],
            organos=[],
            tipos_proy=[],
            tecnologias=[],
            importe_min=0,
            rango=(date(2024, 1, 1), date(2024, 12, 31)),
        )
        result = json.loads(filters_to_json(fs))
        assert result["rango"] == ["2024-01-01", "2024-12-31"]

    def test_with_nav_section_and_detalle_cols(self):
        from db.saved_filters import filters_to_json

        fs = SimpleNamespace(
            q="",
            estados=[],
            ccaas=[],
            organos=[],
            tipos_proy=[],
            tecnologias=[],
            importe_min=0,
            rango=None,
        )
        result = json.loads(filters_to_json(fs, nav_section="sec", detalle_cols=["a", "b"]))
        assert result["nav_section"] == "sec"
        assert result["detalle_cols"] == ["a", "b"]

    def test_no_optional_fields_when_falsy(self):
        from db.saved_filters import filters_to_json

        fs = SimpleNamespace(
            q="",
            estados=[],
            ccaas=[],
            organos=[],
            tipos_proy=[],
            tecnologias=[],
            importe_min=0,
            rango=None,
        )
        result = json.loads(filters_to_json(fs))
        assert "nav_section" not in result
        assert "detalle_cols" not in result


class TestJsonToSessionState:
    def test_full_roundtrip(self):
        from db.saved_filters import json_to_session_state

        d = {
            "q": "search",
            "estados": ["A"],
            "ccaas": ["Madrid"],
            "organos": ["Org"],
            "tipos_proy": ["T"],
            "tecnologias": ["Py"],
            "importe_min": 500,
            "rango": ["2024-01-01", "2024-06-30"],
            "nav_section": "sec",
            "detalle_cols": ["c1"],
        }
        ss = json_to_session_state(json.dumps(d))
        assert ss["fs_q"] == "search"
        assert ss["fs_estados"] == ["A"]
        assert ss["fs_ccaas"] == ["Madrid"]
        assert ss["fs_organos"] == ["Org"]
        assert ss["fs_tipos"] == ["T"]
        assert ss["fs_tecnologias"] == ["Py"]
        assert ss["fs_imp_min"] == 500
        assert ss["fs_rango"] == (date(2024, 1, 1), date(2024, 6, 30))
        assert ss["nav_section"] == "sec"
        assert ss["detalle_cols"] == ["c1"]

    def test_empty_json(self):
        from db.saved_filters import json_to_session_state

        ss = json_to_session_state("{}")
        assert ss == {}

    def test_partial_fields(self):
        from db.saved_filters import json_to_session_state

        ss = json_to_session_state(json.dumps({"q": "hello"}))
        assert ss == {"fs_q": "hello"}

    def test_rango_wrong_length_ignored(self):
        from db.saved_filters import json_to_session_state

        ss = json_to_session_state(json.dumps({"rango": ["2024-01-01"]}))
        assert "fs_rango" not in ss


class TestSaveFilter:
    @patch("db.saved_filters.connect")
    @patch("db.saved_filters.now_utc_iso", return_value="2024-01-01T00:00:00Z")
    def test_save_filter_calls_execute(self, mock_now, mock_connect):
        from db.saved_filters import save_filter

        mock_conn = MagicMock()
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        save_filter("user1", "my_filter", '{"q":"test"}')
        mock_conn.execute.assert_called_once()
        args = mock_conn.execute.call_args
        assert args[0][1] == ("user1", "my_filter", '{"q":"test"}', "2024-01-01T00:00:00Z")


class TestListSavedFilters:
    @patch("db.saved_filters.connect")
    def test_list_returns_dicts(self, mock_connect):
        from db.saved_filters import list_saved_filters

        mock_cursor = MagicMock()
        mock_cursor.description = [("id",), ("name",), ("filters_json",), ("created_at",)]
        mock_cursor.fetchall.return_value = [(1, "f1", "{}", "2024-01-01")]
        mock_conn = MagicMock()
        mock_conn.execute.return_value = mock_cursor
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        result = list_saved_filters("user1")
        assert result == [{"id": 1, "name": "f1", "filters_json": "{}", "created_at": "2024-01-01"}]


class TestDeleteSavedFilter:
    @patch("db.saved_filters.connect")
    def test_delete_calls_execute(self, mock_connect):
        from db.saved_filters import delete_saved_filter

        mock_conn = MagicMock()
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        delete_saved_filter(42)
        mock_conn.execute.assert_called_once()
        assert mock_conn.execute.call_args[0][1] == (42,)


# ═══════════════════════════════════════════════════════════════════════════════
# db.analytics
# ═══════════════════════════════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════════════════════════════
# scheduler.drift_monitor
# ═══════════════════════════════════════════════════════════════════════════════


class TestClassify:
    def test_ok(self):
        from scheduler.drift_monitor import _classify

        sev, _det = _classify(0.0, 0.0)
        assert sev == "ok"

    def test_warn_psi(self):
        from scheduler.drift_monitor import _classify

        sev, _ = _classify(0.12, 0.0)
        assert sev == "warn"

    def test_warn_f1(self):
        from scheduler.drift_monitor import _classify

        sev, _ = _classify(0.0, 0.05)
        assert sev == "warn"

    def test_crit_psi(self):
        from scheduler.drift_monitor import _classify

        sev, _ = _classify(0.30, 0.0)
        assert sev == "crit"

    def test_crit_f1(self):
        from scheduler.drift_monitor import _classify

        sev, _ = _classify(0.0, 0.15)
        assert sev == "crit"


class TestRunOnce:
    @patch("scheduler.drift_monitor.log")
    def test_ok_no_alert(self, mock_log):
        with patch.dict(
            "sys.modules",
            {
                "scheduler.concept_drift": MagicMock(compute_psi=MagicMock(return_value=0.01)),
                "scheduler.drift_report": MagicMock(compute_f1_drop=MagicMock(return_value=0.001)),
            },
        ):
            from scheduler.drift_monitor import run_once

            status = run_once("test_model")
            assert status.severity == "ok"
            assert status.psi == pytest.approx(0.01)

    @patch("scheduler.drift_monitor.log")
    def test_warn_triggers_notify(self, mock_log):
        mock_notify = MagicMock()
        with patch.dict(
            "sys.modules",
            {
                "scheduler.concept_drift": MagicMock(compute_psi=MagicMock(return_value=0.15)),
                "scheduler.drift_report": MagicMock(compute_f1_drop=MagicMock(return_value=0.0)),
                "observability.alerts": MagicMock(notify=mock_notify),
            },
        ):
            from scheduler.drift_monitor import run_once

            status = run_once("m")
            assert status.severity == "warn"
            mock_notify.assert_called_once()

    @patch("scheduler.drift_monitor.log")
    def test_crit_triggers_notify(self, mock_log):
        mock_notify = MagicMock()
        with patch.dict(
            "sys.modules",
            {
                "scheduler.concept_drift": MagicMock(compute_psi=MagicMock(return_value=0.30)),
                "scheduler.drift_report": MagicMock(compute_f1_drop=MagicMock(return_value=0.0)),
                "observability.alerts": MagicMock(notify=mock_notify),
            },
        ):
            from scheduler.drift_monitor import run_once

            status = run_once()
            assert status.severity == "crit"

    @patch("scheduler.drift_monitor.log")
    def test_import_error_psi(self, mock_log):
        """When concept_drift import fails, psi defaults to 0."""
        import sys

        # Remove module so import fails inside run_once
        saved_cd = sys.modules.pop("scheduler.concept_drift", None)
        saved_dr = sys.modules.pop("scheduler.drift_report", None)
        try:
            with patch.dict(
                "sys.modules",
                {
                    "scheduler.concept_drift": None,  # force ImportError
                    "scheduler.drift_report": None,
                },
            ):
                # Need to reimport to trigger the lazy imports inside run_once
                from scheduler.drift_monitor import run_once

                # The function catches ImportError internally
                status = run_once()
                assert status.psi == 0.0
                assert status.f1_drop == 0.0
                assert status.severity == "ok"
        finally:
            if saved_cd:
                sys.modules["scheduler.concept_drift"] = saved_cd
            if saved_dr:
                sys.modules["scheduler.drift_report"] = saved_dr

    @patch("scheduler.drift_monitor.log")
    def test_notify_import_error_handled(self, mock_log):
        """When observability.alerts import fails, it logs warning."""
        with patch.dict(
            "sys.modules",
            {
                "scheduler.concept_drift": MagicMock(compute_psi=MagicMock(return_value=0.30)),
                "scheduler.drift_report": MagicMock(compute_f1_drop=MagicMock(return_value=0.0)),
                "observability.alerts": None,  # force ImportError
            },
        ):
            from scheduler.drift_monitor import run_once

            status = run_once()
            assert status.severity == "crit"
            # Should not raise despite alerts import failure


class TestDriftStatus:
    def test_dataclass(self):
        from scheduler.drift_monitor import DriftStatus

        ds = DriftStatus(psi=0.1, f1_drop=0.05, severity="warn", detail="test")
        assert ds.psi == 0.1
        assert ds.severity == "warn"


# ═══════════════════════════════════════════════════════════════════════════════
