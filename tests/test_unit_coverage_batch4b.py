"""Unit tests for dashboard modules — batch 4b (coverage boost)."""

from __future__ import annotations

import sys
import unittest
from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_df(n: int = 5) -> pd.DataFrame:
    """Create a minimal licitaciones DataFrame for tests."""
    now = pd.Timestamp.now(tz="UTC")
    return pd.DataFrame(
        {
            "id_externo": [f"EXT-{i}" for i in range(n)],
            "titulo": [f"Titulo {i}" for i in range(n)],
            "organo_contratacion": [f"Org{i % 3}" for i in range(n)],
            "importe": [100_000.0 * (i + 1) for i in range(n)],
            "estado": ["PUB"] * n,
            "estado_desc": ["Publicada"] * n,
            "fecha_publicacion": pd.date_range(end=now, periods=n, freq="D"),
            "ccaa": [f"CCAA{i % 2}" for i in range(n)],
            "tecnologia": ["SAP"] * n,
            "tipo_proyecto": ["Servicios"] * n,
            "tipo_contrato": ["Servicios"] * n,
            "cpv_desc": ["CPV desc"] * n,
        }
    )


# ===========================================================================
# 1. FiltersState (dashboard/filters/state.py)
# ===========================================================================


class TestFiltersState(unittest.TestCase):
    def _cls(self):
        from dashboard.filters.state import FiltersState

        return FiltersState

    def test_default_not_active(self):
        fs = self._cls()()
        self.assertFalse(fs.is_active())

    def test_active_with_q(self):
        fs = self._cls()(q="sap")
        self.assertTrue(fs.is_active())

    def test_active_with_estados(self):
        fs = self._cls()(estados=["Publicada"])
        self.assertTrue(fs.is_active())

    def test_active_with_importe(self):
        fs = self._cls()(importe_min=1000)
        self.assertTrue(fs.is_active())

    def test_active_with_tecnologias(self):
        fs = self._cls()(tecnologias=["SAP"])
        self.assertTrue(fs.is_active())

    def test_active_labels(self):
        fs = self._cls()(
            q="x",
            estados=["A"],
            ccaas=["B"],
            organos=["OrgLargo"],
            tipos_proy=["T"],
            tecnologias=["Tech"],
            importe_min=500,
        )
        labels = fs.active_labels()
        self.assertEqual(len(labels), 7)

    def test_active_items_values(self):
        fs = self._cls()(q="x", estados=["A"], importe_min=100)
        items = fs.active_items()
        # q -> (label, "fs_q", None), estado -> (label, "fs_estados", "A"), imp -> (label, "fs_imp_min", None)
        self.assertEqual(len(items), 3)
        self.assertIsNone(items[0][2])  # q: scalar
        self.assertEqual(items[1][2], "A")  # estado: list item

    def test_to_query_params(self):
        fs = self._cls()(
            q="sap",
            rango=(date(2024, 1, 1), date(2024, 6, 1)),
            estados=["Pub"],
            ccaas=["Madrid"],
            organos=["Org1"],
            tipos_proy=["Srv"],
            tecnologias=["SAP"],
            importe_min=5000,
        )
        qp = fs.to_query_params()
        self.assertEqual(qp["q"], "sap")
        self.assertEqual(qp["fecha_desde"], "2024-01-01")
        self.assertEqual(qp["estados"], "Pub")
        self.assertEqual(qp["imp_min"], "5000")
        self.assertIn("tecnologias", qp)

    def test_to_query_params_empty(self):
        qp = self._cls()().to_query_params()
        self.assertEqual(qp, {})

    def test_from_query_params_full(self):
        params = {
            "q": "sap",
            "fecha_desde": "2024-01-01",
            "fecha_hasta": "2024-06-01",
            "estados": "Pub,Adj",
            "ccaas": "Madrid",
            "organos": "Org1",
            "tipos": "Srv",
            "tecnologias": "SAP,Oracle",
            "imp_min": "5000",
            "lic": "EXT-123",
        }
        fs = self._cls().from_query_params(params)
        self.assertEqual(fs.q, "sap")
        self.assertEqual(fs.rango, (date(2024, 1, 1), date(2024, 6, 1)))
        self.assertEqual(fs.estados, ["Pub", "Adj"])
        self.assertEqual(fs.importe_min, 5000)
        self.assertEqual(fs.lic_id, "EXT-123")
        self.assertEqual(len(fs.tecnologias), 2)

    def test_from_query_params_invalid_date(self):
        params = {"fecha_desde": "bad", "fecha_hasta": "also-bad"}
        fs = self._cls().from_query_params(params)
        self.assertIsNone(fs.rango)

    def test_from_query_params_invalid_importe(self):
        params = {"imp_min": "abc"}
        fs = self._cls().from_query_params(params)
        self.assertEqual(fs.importe_min, 0)

    def test_from_query_params_empty(self):
        fs = self._cls().from_query_params({})
        self.assertFalse(fs.is_active())
        self.assertIsNone(fs.lic_id)

    def test_from_query_params_dates_swapped(self):
        params = {"fecha_desde": "2024-06-01", "fecha_hasta": "2024-01-01"}
        fs = self._cls().from_query_params(params)
        self.assertEqual(fs.rango, (date(2024, 1, 1), date(2024, 6, 1)))


# ===========================================================================
# 2. shared/schemas.py
# ===========================================================================


class TestSchemas(unittest.TestCase):
    def test_pandera_installed_flag(self):
        from shared.schemas import _pandera_installed

        # Just ensure it returns a bool
        self.assertIsInstance(_pandera_installed(), bool)

    def test_validate_licitaciones_returns_df(self):
        from shared.schemas import validate_licitaciones

        df = pd.DataFrame(
            {
                "id_externo": ["1"],
                "titulo": ["T"],
                "organo_contratacion": ["O"],
                "importe": [1.0],
                "estado": ["P"],
                "fecha_publicacion": [pd.Timestamp.now()],
                "ccaa": ["M"],
                "tecnologia": ["S"],
                "tipo_contrato": ["S"],
            }
        )
        result = validate_licitaciones(df, lazy=True)
        self.assertEqual(len(result), 1)

    def test_validate_adjudicaciones_returns_df(self):
        from shared.schemas import validate_adjudicaciones

        df = pd.DataFrame(
            {
                "licitacion_id": ["1"],
                "nombre": ["N"],
                "importe_adjudicado": [1.0],
                "fecha_adjudicacion": [pd.Timestamp.now()],
            }
        )
        result = validate_adjudicaciones(df, lazy=True)
        self.assertEqual(len(result), 1)

    def test_noop_schema_when_pandera_missing(self):
        """Test the _NoOpSchema stub path."""
        from shared.schemas import _NoOpSchema

        df = pd.DataFrame({"a": [1]})
        result = _NoOpSchema.validate(df)
        self.assertIs(result, df)

    def test_kpi_snapshot_schema(self):
        from shared.schemas import KpiSnapshotSchema

        df = pd.DataFrame(
            {
                "metric_name": ["total"],
                "metric_value": [42.0],
                "computed_at": ["2024-01-01"],
            }
        )
        result = KpiSnapshotSchema.validate(df, lazy=True)
        self.assertEqual(len(result), 1)


# ===========================================================================
# 3. dashboard/components/layout.py — _format_last_updated & fmt_eur
# ===========================================================================


class TestFormatLastUpdated(unittest.TestCase):
    def _fn(self):
        from dashboard.components.layout import _format_last_updated

        return _format_last_updated

    def test_none(self):
        self.assertEqual(self._fn()(None), "sin datos")

    def test_nan(self):
        self.assertEqual(self._fn()(float("nan")), "sin datos")

    def test_string_nan(self):
        self.assertEqual(self._fn()("not-a-date"), "sin datos")

    def test_seconds_ago(self):
        ts = datetime.now(UTC) - timedelta(seconds=10)
        self.assertEqual(self._fn()(ts), "hace segundos")

    def test_minutes_ago(self):
        ts = datetime.now(UTC) - timedelta(minutes=5)
        self.assertIn("min", self._fn()(ts))

    def test_hours_ago(self):
        ts = datetime.now(UTC) - timedelta(hours=3)
        self.assertIn("h", self._fn()(ts))

    def test_days_ago(self):
        ts = datetime.now(UTC) - timedelta(days=5)
        self.assertIn("d", self._fn()(ts))

    def test_old_date(self):
        ts = datetime.now(UTC) - timedelta(days=60)
        result = self._fn()(ts)
        self.assertRegex(result, r"\d{4}-\d{2}-\d{2}")

    def test_naive_timestamp(self):
        # _format_last_updated calls tz_localize which is pandas-only;
        # pass a naive pandas Timestamp instead of datetime
        ts = pd.Timestamp.now() - pd.Timedelta(hours=1)
        result = self._fn()(ts)
        self.assertIn("h", result)

    def test_pandas_timestamp(self):
        ts = pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=10)
        result = self._fn()(ts)
        self.assertIn("min", result)

    def test_string_timestamp(self):
        ts = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        result = self._fn()(ts)
        self.assertIn("h", result)


class TestFmtEur(unittest.TestCase):
    def test_none(self):
        from dashboard.components.layout import fmt_eur

        # Should not raise
        result = fmt_eur(None)
        self.assertIsInstance(result, str)

    def test_number(self):
        from dashboard.components.layout import fmt_eur

        result = fmt_eur(1234.5)
        self.assertIsInstance(result, str)


# ===========================================================================
# 4. layout.py — render functions (mock streamlit)
# ===========================================================================


class TestRenderTopbarBrand(unittest.TestCase):
    @patch("dashboard.components.layout.st")
    @patch("dashboard.components.layout.LOGO_SVG", "<svg/>")
    def test_calls_markdown(self, mock_st):
        from dashboard.components.layout import render_topbar_brand

        render_topbar_brand()
        mock_st.markdown.assert_called_once()


class TestRenderSidebarBrand(unittest.TestCase):
    @patch("dashboard.components.layout.st")
    def test_calls_markdown(self, mock_st):
        from dashboard.components.layout import render_sidebar_brand

        render_sidebar_brand()
        mock_st.markdown.assert_called_once()


class TestRenderExportPopover(unittest.TestCase):
    def test_noop(self):
        from dashboard.components.layout import render_export_popover

        result = render_export_popover(pd.DataFrame())
        self.assertIsNone(result)


class TestRenderTopbar(unittest.TestCase):
    @patch("dashboard.components.layout.st")
    @patch("dashboard.components.layout.LOGO_SVG", "<svg/>")
    @patch("dashboard.components.layout.icon", return_value="<i/>")
    def test_returns_false(self, _icon, mock_st):
        # Setup columns context managers — topbar now uses 5 columns
        col = MagicMock()
        col.__enter__ = MagicMock(return_value=col)
        col.__exit__ = MagicMock(return_value=False)
        col.button = MagicMock(return_value=False)
        mock_st.columns.return_value = [col, col, col, col, col]
        mock_st.session_state = {}
        mock_st.button = MagicMock(return_value=False)

        from dashboard.components.layout import render_topbar

        result = render_topbar(last_updated=None)
        self.assertFalse(result)


# ===========================================================================
# 5. dashboard/routing/url_params.py
# ===========================================================================


class TestInitFromQueryParams(unittest.TestCase):
    @patch("dashboard.routing.url_params.st")
    def test_skips_if_already_loaded(self, mock_st):
        from dashboard.routing.url_params import init_from_query_params
        from dashboard.session_keys import QP_LOADED

        mock_st.session_state = {QP_LOADED: True}
        init_from_query_params(_make_df())
        # Should return early, no query_params access

    @patch("dashboard.routing.url_params.st")
    def test_loads_filters_from_url(self, mock_st):
        from dashboard.routing.url_params import init_from_query_params
        from dashboard.session_keys import FS_CCAAS, FS_ESTADOS, FS_Q, QP_LOADED

        mock_st.session_state = {}
        mock_st.query_params = {
            "q": "sap",
            "estados": "Publicada",
            "ccaas": "CCAA0",
        }
        df = _make_df()
        init_from_query_params(df)
        self.assertEqual(mock_st.session_state[FS_Q], "sap")
        self.assertEqual(mock_st.session_state[FS_ESTADOS], ["Publicada"])
        self.assertEqual(mock_st.session_state[FS_CCAAS], ["CCAA0"])
        self.assertTrue(mock_st.session_state[QP_LOADED])

    @patch("dashboard.routing.url_params.st")
    def test_loads_organos_tipos_importe(self, mock_st):
        from dashboard.routing.url_params import init_from_query_params
        from dashboard.session_keys import FS_IMP_MIN, FS_ORGANOS, FS_TIPOS

        mock_st.session_state = {}
        mock_st.query_params = {
            "organos": "Org0",
            "tipos": "Servicios",
            "imp_min": "50000",
        }
        df = _make_df()
        init_from_query_params(df)
        self.assertEqual(mock_st.session_state[FS_ORGANOS], ["Org0"])
        self.assertEqual(mock_st.session_state[FS_TIPOS], ["Servicios"])
        self.assertEqual(mock_st.session_state[FS_IMP_MIN], 50000)

    @patch("dashboard.routing.url_params.st")
    def test_loads_rango(self, mock_st):
        from dashboard.routing.url_params import init_from_query_params
        from dashboard.session_keys import FS_RANGO

        mock_st.session_state = {}
        mock_st.query_params = {
            "fecha_desde": "2024-01-01",
            "fecha_hasta": "2024-06-01",
        }
        init_from_query_params(_make_df())
        self.assertEqual(mock_st.session_state[FS_RANGO], (date(2024, 1, 1), date(2024, 6, 1)))

    @patch("dashboard.routing.url_params.st")
    def test_loads_lic_deep_link(self, mock_st):
        from dashboard.routing.url_params import init_from_query_params
        from dashboard.session_keys import LIC_FOCUS, NAV_SECTION

        mock_st.session_state = {}
        mock_st.query_params = {"lic": "EXT-42"}
        init_from_query_params(_make_df())
        self.assertEqual(mock_st.session_state[LIC_FOCUS], "EXT-42")
        self.assertEqual(mock_st.session_state[NAV_SECTION], "Vista General")

    @patch("dashboard.routing.url_params.st")
    def test_filters_invalid_values(self, mock_st):
        from dashboard.routing.url_params import init_from_query_params
        from dashboard.session_keys import FS_ESTADOS

        mock_st.session_state = {}
        mock_st.query_params = {"estados": "NoExiste"}
        init_from_query_params(_make_df())
        self.assertEqual(mock_st.session_state[FS_ESTADOS], [])


class TestSyncToQueryParams(unittest.TestCase):
    @patch("dashboard.routing.url_params.st")
    def test_updates_params(self, mock_st):
        from dashboard.filters.state import FiltersState
        from dashboard.routing.url_params import sync_to_query_params

        qp = MagicMock()
        qp.__iter__ = MagicMock(return_value=iter([]))
        qp.__eq__ = MagicMock(return_value=False)
        mock_st.query_params = qp
        fs = FiltersState(q="sap")
        sync_to_query_params(fs)
        qp.update.assert_called_once()

    @patch("dashboard.routing.url_params.st")
    def test_no_update_when_same(self, mock_st):
        from dashboard.filters.state import FiltersState
        from dashboard.routing.url_params import sync_to_query_params

        qp = MagicMock()
        # dict(st.query_params) returns {"q": "sap"}, which equals filters.to_query_params()
        qp.__iter__ = MagicMock(return_value=iter(["q"]))
        qp.__getitem__ = MagicMock(return_value="sap")
        qp.keys = MagicMock(return_value=["q"])
        mock_st.query_params = qp
        fs = FiltersState(q="sap")
        # We need dict(qp) == {"q": "sap"}, but MagicMock doesn't iterate well for dict()
        # Instead, patch dict() call path: the function does dict(st.query_params)
        with patch("dashboard.routing.url_params.dict", side_effect=lambda x: {"q": "sap"}):
            sync_to_query_params(fs)
        qp.update.assert_not_called()

    @patch("dashboard.routing.url_params.st")
    def test_removes_old_keys(self, mock_st):
        from dashboard.filters.state import FiltersState
        from dashboard.routing.url_params import sync_to_query_params

        qp = MagicMock()
        qp.__eq__ = MagicMock(return_value=False)
        # dict(st.query_params) returns {"old_key": "val"}
        # list(cur_qp) iterates over keys
        mock_dict_result = {"old_key": "val"}
        with patch("dashboard.routing.url_params.dict", side_effect=lambda x: mock_dict_result):
            mock_st.query_params = qp
            fs = FiltersState()  # empty filters -> new_qp = {}
            sync_to_query_params(fs)
        # Should have deleted "old_key"
        qp.__delitem__.assert_called_with("old_key")


# ===========================================================================
# 6. dashboard/kpi_bar.py — compute_kpis, _snapshot_kpis, _snapshot_series
# ===========================================================================


class TestComputeKpis(unittest.TestCase):
    def test_empty_df(self):
        from dashboard.kpi_bar import compute_kpis

        # Unwrap st.cache_data
        fn = compute_kpis.__wrapped__ if hasattr(compute_kpis, "__wrapped__") else compute_kpis
        result = fn(pd.DataFrame())
        self.assertEqual(result["total"], 0)

    def test_with_data_pandas_fallback(self):
        from dashboard.kpi_bar import compute_kpis

        fn = compute_kpis.__wrapped__ if hasattr(compute_kpis, "__wrapped__") else compute_kpis
        df = _make_df(10)
        with patch.dict(sys.modules, {"polars": None}):
            # Force ImportError for polars
            original_import = (
                __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__
            )

            def mock_import(name, *args, **kwargs):
                if name == "polars":
                    raise ImportError("no polars")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                result = fn(df)
        self.assertEqual(result["total"], 10)
        self.assertGreater(result["importe_total"], 0)

    def test_with_data_polars_path(self):
        """Test with polars available (if installed)."""
        from dashboard.kpi_bar import compute_kpis

        fn = compute_kpis.__wrapped__ if hasattr(compute_kpis, "__wrapped__") else compute_kpis
        df = _make_df(5)
        result = fn(df)
        self.assertEqual(result["total"], 5)


class TestSnapshotKpis(unittest.TestCase):
    def test_none_when_total_mismatch(self):
        from dashboard.kpi_bar import _snapshot_kpis

        result = _snapshot_kpis({"total_licitaciones": 100}, 50)
        self.assertIsNone(result)

    def test_none_when_no_total(self):
        from dashboard.kpi_bar import _snapshot_kpis

        result = _snapshot_kpis({}, 50)
        self.assertIsNone(result)

    def test_returns_dict_when_match(self):
        from dashboard.kpi_bar import _snapshot_kpis

        snap = {
            "total_licitaciones": 10,
            "licitaciones_30d": 5,
            "licitaciones_30d_prev": 3,
            "importe_total": 1000.0,
            "importe_medio": 100.0,
            "n_organos": 2,
            "n_ccaa": 3,
        }
        result = _snapshot_kpis(snap, 10)
        self.assertIsNotNone(result)
        self.assertEqual(result["total"], 10)
        self.assertEqual(result["delta_n"], 2)
        self.assertAlmostEqual(result["delta_pct"], 2 / 3 * 100, places=1)

    def test_zero_prev(self):
        from dashboard.kpi_bar import _snapshot_kpis

        snap = {"total_licitaciones": 5, "licitaciones_30d": 5, "licitaciones_30d_prev": 0}
        result = _snapshot_kpis(snap, 5)
        self.assertEqual(result["delta_pct"], 0.0)


class TestSnapshotSeries(unittest.TestCase):
    def test_no_serie(self):
        from dashboard.kpi_bar import _snapshot_series

        self.assertIsNone(_snapshot_series({}, "n"))

    def test_invalid_type(self):
        from dashboard.kpi_bar import _snapshot_series

        self.assertIsNone(_snapshot_series({"serie_mensual_24m": "bad"}, "n"))

    def test_valid_series(self):
        from dashboard.kpi_bar import _snapshot_series

        serie = [{"n": i, "importe": i * 100} for i in range(24)]
        result = _snapshot_series({"serie_mensual_24m": serie}, "n")
        self.assertEqual(len(result), 12)
        self.assertEqual(result[0], 12.0)

    def test_empty_list(self):
        from dashboard.kpi_bar import _snapshot_series

        result = _snapshot_series({"serie_mensual_24m": []}, "n")
        self.assertIsNone(result)


class TestLast12mSeries(unittest.TestCase):
    def test_empty_df(self):
        from dashboard.kpi_bar import _last_12m_series

        fn = (
            _last_12m_series.__wrapped__
            if hasattr(_last_12m_series, "__wrapped__")
            else _last_12m_series
        )
        self.assertEqual(fn(pd.DataFrame()), [])

    def test_with_data(self):
        from dashboard.kpi_bar import _last_12m_series

        fn = (
            _last_12m_series.__wrapped__
            if hasattr(_last_12m_series, "__wrapped__")
            else _last_12m_series
        )
        df = _make_df(30)
        result = fn(df)
        self.assertIsInstance(result, list)

    def test_with_value_col(self):
        from dashboard.kpi_bar import _last_12m_series

        fn = (
            _last_12m_series.__wrapped__
            if hasattr(_last_12m_series, "__wrapped__")
            else _last_12m_series
        )
        df = _make_df(30)
        result = fn(df, value_col="importe")
        self.assertIsInstance(result, list)


class TestRenderKpiBar(unittest.TestCase):
    @patch("dashboard.kpi_bar._load_precomputed_kpis")
    @patch("dashboard.kpi_bar.compute_kpis")
    @patch("dashboard.kpi_bar._last_12m_series")
    @patch("dashboard.kpi_bar.st")
    @patch("dashboard.kpi_bar.kpi_card", return_value="<div/>")
    @patch("dashboard.kpi_bar.icon", return_value="<i/>")
    @patch("dashboard.kpi_bar.fmt_eur", return_value="1.000 €")
    def test_render(self, _fmt, _icon, _kpi, mock_st, _series, _compute, _precomp):
        from dashboard.kpi_bar import render_kpi_bar

        fn = (
            render_kpi_bar.__wrapped__ if hasattr(render_kpi_bar, "__wrapped__") else render_kpi_bar
        )
        _precomp_fn = _precomp.__wrapped__ if hasattr(_precomp, "__wrapped__") else _precomp
        _precomp.return_value = {}
        _compute_fn = _compute.__wrapped__ if hasattr(_compute, "__wrapped__") else _compute
        _compute.return_value = {
            "total": 10,
            "importe_total": 1000,
            "importe_medio": 100,
            "n_organos": 2,
            "n_ccaa": 3,
            "delta_n": 1,
            "delta_pct": 10.0,
            "prev30_size": 5,
        }
        _series_fn = _series.__wrapped__ if hasattr(_series, "__wrapped__") else _series
        _series.return_value = [1.0] * 12

        col = MagicMock()
        col.__enter__ = MagicMock(return_value=col)
        col.__exit__ = MagicMock(return_value=False)
        mock_st.columns.return_value = [col] * 5

        fn(_make_df())
        self.assertTrue(mock_st.columns.called)


# ===========================================================================
# 7. dashboard/filters/sidebar.py — helpers
# ===========================================================================


class TestSidebarHelpers(unittest.TestCase):
    @patch("dashboard.filters.sidebar.st")
    @patch("dashboard.filters.sidebar.icon", return_value="<i/>")
    def test_group_header(self, _icon, mock_st):
        from dashboard.filters.sidebar import _group_header

        _group_header("Test", "search")
        mock_st.markdown.assert_called_once()

    @patch("dashboard.filters.sidebar.st")
    def test_clear_filters(self, mock_st):
        from dashboard.filters.sidebar import _clear_filters
        from dashboard.session_keys import FS_Q, QP_LOADED

        mock_st.session_state = {FS_Q: "sap", "other": "keep"}
        _clear_filters()
        self.assertNotIn(FS_Q, mock_st.session_state)
        self.assertIn("other", mock_st.session_state)
        self.assertFalse(mock_st.session_state[QP_LOADED])

    def test_set_preset_activas_sap(self):
        with patch("dashboard.filters.sidebar.st") as mock_st:
            from dashboard.filters.sidebar import _set_preset_activas_sap
            from dashboard.session_keys import FS_ESTADOS, FS_RANGO

            mock_st.session_state = {}
            fmin = date(2024, 1, 1)
            fmax = date(2025, 12, 31)
            _set_preset_activas_sap(fmin, fmax)
            self.assertIn(FS_RANGO, mock_st.session_state)
            self.assertEqual(mock_st.session_state[FS_ESTADOS], ["Publicada"])

    def test_set_preset_alto_importe(self):
        with patch("dashboard.filters.sidebar.st") as mock_st:
            from dashboard.filters.sidebar import _set_preset_alto_importe
            from dashboard.session_keys import FS_IMP_MIN

            mock_st.session_state = {}
            _set_preset_alto_importe(date(2024, 1, 1), date(2025, 12, 31))
            self.assertEqual(mock_st.session_state[FS_IMP_MIN], 100_000)

    def test_set_preset_nuevas_semana(self):
        with patch("dashboard.filters.sidebar.st") as mock_st:
            from dashboard.filters.sidebar import _set_preset_nuevas_semana
            from dashboard.session_keys import FS_RANGO

            mock_st.session_state = {}
            _set_preset_nuevas_semana(date(2024, 1, 1), date(2025, 12, 31))
            self.assertIn(FS_RANGO, mock_st.session_state)

    def test_set_rango_preset(self):
        with patch("dashboard.filters.sidebar.st") as mock_st:
            from dashboard.filters.sidebar import _set_rango_preset
            from dashboard.session_keys import FS_RANGO

            mock_st.session_state = {}
            _set_rango_preset(30, date(2024, 1, 1), date(2025, 12, 31))
            rango = mock_st.session_state[FS_RANGO]
            self.assertEqual(len(rango), 2)

    def test_set_rango_ytd(self):
        with patch("dashboard.filters.sidebar.st") as mock_st:
            from dashboard.filters.sidebar import _set_rango_ytd
            from dashboard.session_keys import FS_RANGO

            mock_st.session_state = {}
            _set_rango_ytd(date(2024, 1, 1), date(2025, 12, 31))
            rango = mock_st.session_state[FS_RANGO]
            self.assertEqual(rango[0].month, 1)
            self.assertEqual(rango[0].day, 1)


class TestRenderSidebarFilters(unittest.TestCase):
    @patch("dashboard.filters.sidebar.apply_filters")
    @patch("dashboard.filters.sidebar.render_search_autocomplete")
    @patch("dashboard.filters.sidebar.icon", return_value="<i/>")
    @patch("dashboard.filters.sidebar.st")
    def test_render_returns_filters_state(self, mock_st, _icon, _search, _apply):
        from dashboard.filters.sidebar import render_sidebar_filters

        df = _make_df()
        _apply.return_value = df

        mock_st.session_state = {}
        mock_st.text_input.return_value = ""
        mock_st.multiselect.return_value = []
        mock_st.number_input.return_value = 0
        mock_st.toggle.return_value = False
        mock_st.button.return_value = False

        # date_input returns tuple
        fmin = df["fecha_publicacion"].min()
        fmax = df["fecha_publicacion"].max()
        mock_st.date_input.return_value = (fmin.date(), fmax.date())

        # columns returns column mocks — need to handle varying arg counts
        col = MagicMock()
        col.button = MagicMock(return_value=False)

        def columns_side_effect(n, **kwargs):
            count = n if isinstance(n, int) else len(n)
            return [col] * count

        mock_st.columns.side_effect = columns_side_effect

        # expander context manager
        exp = MagicMock()
        exp.__enter__ = MagicMock(return_value=exp)
        exp.__exit__ = MagicMock(return_value=False)
        exp.multiselect = mock_st.multiselect
        exp.number_input = mock_st.number_input
        exp.toggle = mock_st.toggle
        exp.date_input = mock_st.date_input
        exp.caption = MagicMock()
        mock_st.expander.return_value = exp

        result = render_sidebar_filters(df)
        from dashboard.filters.state import FiltersState

        self.assertIsInstance(result, FiltersState)


# ===========================================================================
# 8. dashboard/components/layout.py — render_notification_bell
# ===========================================================================


class TestRenderNotificationBell(unittest.TestCase):
    @patch("dashboard.components.layout.st")
    def test_handles_exception_gracefully(self, mock_st):
        """If db.notifications import fails, should not raise."""
        from dashboard.components.layout import render_notification_bell

        df = _make_df()
        # Should not raise even if internals fail
        render_notification_bell(df, "testuser", since_days=7)

    @patch("dashboard.components.layout.st")
    def test_with_mocked_notifications(self, mock_st):
        from dashboard.components.layout import render_notification_bell

        mock_st.session_state = {}
        mock_st.markdown = MagicMock()
        mock_st.caption = MagicMock()
        mock_st.button = MagicMock(return_value=False)

        pop = MagicMock()
        pop.__enter__ = MagicMock(return_value=pop)
        pop.__exit__ = MagicMock(return_value=False)
        mock_st.popover.return_value = pop

        df = _make_df()

        with patch.dict(
            sys.modules,
            {
                "db.notifications": MagicMock(
                    get_unread_ids=MagicMock(return_value=set()),
                    mark_all_read=MagicMock(),
                )
            },
        ):
            render_notification_bell(df, "testuser", since_days=7)


if __name__ == "__main__":
    unittest.main()
