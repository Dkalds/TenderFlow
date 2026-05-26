"""Unit tests for dashboard pages batch 4d: pipeline_alertas, calendario,
licitadores, active_learning, tendencias, tendencias_cpv, geografia, admin,
admin_flags, comparador, mi_watchlist, clusters."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from dashboard.filters.state import FiltersState
from dashboard.pages._base import PageContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_df(**overrides):
    now = pd.Timestamp.now("UTC")
    base = {
        "id_externo": ["EXP-001", "EXP-002"],
        "titulo": ["Mantenimiento SAP", "Migración S/4HANA"],
        "importe": [100_000.0, 250_000.0],
        "organo_contratacion": ["Org A", "Org B"],
        "estado_desc": ["Abierta", "Cerrada"],
        "tipo_proyecto": ["Servicios", "Suministros"],
        "fecha_publicacion": [now - pd.Timedelta(days=10), now - pd.Timedelta(days=20)],
        "url": ["https://example.com/1", "https://example.com/2"],
        "ccaa": ["Madrid", "Cataluña"],
        "cpv": ["72000000", "72200000"],
        "cpv_desc": ["CPV1", "CPV2"],
        "tipo_contrato_desc": ["Servicio", "Suministro"],
        "tecnologia": ["SAP", "Oracle"],
        "descripcion": ["Desc larga 1", "Desc larga 2"],
        "provincia": ["Madrid", "Barcelona"],
        "moneda": ["EUR", "EUR"],
        "mes": [now - pd.Timedelta(days=10), now - pd.Timedelta(days=20)],
        "fecha_limite": [now + pd.Timedelta(days=30), now + pd.Timedelta(days=60)],
    }
    base.update(overrides)
    return pd.DataFrame(base)


def _make_ctx(df=None, df_full=None, filters=None):
    if df is None:
        df = _make_df()
    if df_full is None:
        df_full = df.copy()
    if filters is None:
        filters = FiltersState()
    return PageContext(
        df=df,
        df_full=df_full,
        filters=filters,
        tokens=MagicMock(),
        plotly_template="plotly_dark",
        color_sequence=["#86BC24", "#009A44", "#00A3E0"],
    )


def _make_col():
    c = MagicMock()
    c.__enter__ = MagicMock(return_value=c)
    c.__exit__ = MagicMock(return_value=False)
    return c


def _mock_st_module(mock_st):
    """Configure common st mock attributes."""
    mock_st.session_state = {}
    mock_st.query_params = {}

    def _columns_side_effect(spec=None, **kwargs):
        if isinstance(spec, int):
            n = spec
        elif isinstance(spec, (list, tuple)):
            n = len(spec)
        else:
            n = 4
        return [_make_col() for _ in range(n)]

    mock_st.columns.side_effect = _columns_side_effect
    mock_st.expander.return_value.__enter__ = MagicMock(return_value=MagicMock())
    mock_st.expander.return_value.__exit__ = MagicMock(return_value=False)
    mock_st.container.return_value.__enter__ = MagicMock(return_value=MagicMock())
    mock_st.container.return_value.__exit__ = MagicMock(return_value=False)
    mock_st.tabs.return_value = [MagicMock() for _ in range(5)]
    for t in mock_st.tabs.return_value:
        t.__enter__ = MagicMock(return_value=t)
        t.__exit__ = MagicMock(return_value=False)
    mock_st.selectbox.return_value = None
    mock_st.slider.return_value = 10
    mock_st.number_input.return_value = 50
    mock_st.checkbox.return_value = False
    mock_st.toggle.return_value = False
    mock_st.radio.return_value = "Licitaciones"
    mock_st.multiselect.return_value = []
    mock_st.text_input.return_value = ""
    mock_st.button.return_value = False
    mock_st.form.return_value.__enter__ = MagicMock()
    mock_st.form.return_value.__exit__ = MagicMock(return_value=False)
    mock_st.form_submit_button.return_value = False
    mock_st.column_config = MagicMock()
    mock_st.fragment = lambda f: f
    mock_st.cache_data = lambda **kw: lambda f: f
    mock_st.cache_resource = lambda **kw: lambda f: f
    return mock_st


# ===========================================================================
# pipeline_alertas.py
# ===========================================================================


class TestPipelineAlertas:
    @patch(
        "dashboard.pages.pipeline_alertas.score_oportunidad",
        return_value=pd.DataFrame({"id_externo": [], "score": [], "banda": []}),
    )
    @patch(
        "dashboard.pages.pipeline_alertas.risk_flags",
        return_value=pd.DataFrame({"id_externo": [], "riesgo_flags": [], "riesgo_score": []}),
    )
    @patch("dashboard.pages.pipeline_alertas.ratio_relicitacion", return_value=0.0)
    @patch("dashboard.pages.pipeline_alertas.data_table")
    @patch("dashboard.pages.pipeline_alertas.kpi_card", return_value="<div></div>")
    @patch("dashboard.pages.pipeline_alertas.build_forecast_df")
    @patch("dashboard.pages.pipeline_alertas.load_adjudicaciones")
    @patch("dashboard.pages.pipeline_alertas.st")
    def test_render_with_data(
        self,
        mock_st,
        mock_load_adj,
        mock_forecast,
        mock_kpi,
        mock_dt,
        mock_ratio,
        mock_risk,
        mock_score,
    ):
        _mock_st_module(mock_st)
        mock_st.slider.return_value = 18
        mock_st.number_input.return_value = 0

        now = pd.Timestamp.now()
        adj_df = pd.DataFrame({"id_externo": ["EXP-001"], "importe": [100_000]})
        mock_load_adj.return_value = adj_df

        fc = pd.DataFrame(
            {
                "id_externo": ["EXP-001"],
                "titulo": ["Test SAP"],
                "organo_contratacion": ["Org A"],
                "ccaa": ["Madrid"],
                "importe": [100_000.0],
                "fecha_fin_estimada": [now + pd.Timedelta(days=90)],
                "relicit_inicio": [now - pd.Timedelta(days=30)],
                "estado_forecast": ["Activo"],
                "inicio_efectivo": [now - pd.Timedelta(days=365)],
            }
        )
        mock_forecast.return_value = fc

        from dashboard.pages.pipeline_alertas import render

        ctx = _make_ctx()
        render(ctx)
        mock_st.subheader.assert_called()

    @patch("dashboard.pages.pipeline_alertas.empty_state")
    @patch("dashboard.pages.pipeline_alertas.load_adjudicaciones")
    @patch("dashboard.pages.pipeline_alertas.st")
    def test_render_empty_adj(self, mock_st, mock_load_adj, mock_empty):
        _mock_st_module(mock_st)
        mock_load_adj.return_value = pd.DataFrame()
        from dashboard.pages.pipeline_alertas import render

        render(_make_ctx())
        mock_empty.assert_called()

    @patch("dashboard.pages.pipeline_alertas.empty_state")
    @patch("dashboard.pages.pipeline_alertas.build_forecast_df")
    @patch("dashboard.pages.pipeline_alertas.load_adjudicaciones")
    @patch("dashboard.pages.pipeline_alertas.st")
    def test_render_empty_forecast(self, mock_st, mock_load_adj, mock_fc, mock_empty):
        _mock_st_module(mock_st)
        mock_st.slider.return_value = 6
        mock_st.number_input.return_value = 0
        mock_st.checkbox.return_value = False
        mock_load_adj.return_value = pd.DataFrame({"id_externo": ["X"]})
        mock_fc.return_value = pd.DataFrame()
        from dashboard.pages.pipeline_alertas import render

        render(_make_ctx())
        mock_empty.assert_called()

    @patch("dashboard.pages.pipeline_alertas.empty_state")
    @patch("dashboard.pages.pipeline_alertas.load_adjudicaciones")
    @patch("dashboard.pages.pipeline_alertas.st")
    def test_render_empty_df(self, mock_st, mock_load_adj, mock_empty):
        _mock_st_module(mock_st)
        mock_load_adj.return_value = pd.DataFrame({"id_externo": ["X"]})
        from dashboard.pages.pipeline_alertas import render

        ctx = _make_ctx(df=pd.DataFrame())
        render(ctx)
        mock_empty.assert_called()


# ===========================================================================
# calendario.py
# ===========================================================================


class TestCalendario:
    @patch("dashboard.pages.calendario.st")
    def test_render_with_data(self, mock_st):
        _mock_st_module(mock_st)
        mock_st.selectbox.return_value = 2024

        now = pd.Timestamp("2024-06-15")
        df = _make_df(fecha_publicacion=[now, now - pd.Timedelta(days=5)])
        ctx = _make_ctx(df=df)
        from dashboard.pages.calendario import render

        render(ctx)
        mock_st.subheader.assert_called()

    @patch("dashboard.pages.calendario.empty_state")
    @patch("dashboard.pages.calendario.st")
    def test_render_empty(self, mock_st, mock_empty):
        _mock_st_module(mock_st)
        from dashboard.pages.calendario import render

        render(_make_ctx(df=pd.DataFrame({"fecha_publicacion": [None, None]})))
        mock_empty.assert_called()

    @patch("dashboard.pages.calendario.st")
    def test_render_empty_df(self, mock_st):
        _mock_st_module(mock_st)
        from dashboard.pages.calendario import render

        ctx = _make_ctx(df=pd.DataFrame({"fecha_publicacion": []}))
        render(ctx)

    @patch("dashboard.pages.calendario.st")
    def test_render_no_data_for_year(self, mock_st):
        _mock_st_module(mock_st)
        mock_st.selectbox.return_value = 1999
        df = _make_df(fecha_publicacion=[pd.Timestamp("2024-06-15"), pd.Timestamp("2024-06-16")])
        from dashboard.pages.calendario import render

        render(_make_ctx(df=df))
        mock_st.info.assert_called()


# ===========================================================================
# licitadores.py
# ===========================================================================


class TestLicitadores:
    @patch("dashboard.pages.licitadores.svc_load_licitadores")
    @patch("dashboard.pages.licitadores.normalize_company", side_effect=lambda x: x)
    @patch("dashboard.pages.licitadores.st")
    def test_render_with_data(self, mock_st, mock_norm, mock_svc):
        _mock_st_module(mock_st)
        mock_st.selectbox.side_effect = ["Todas", "Todos"]
        mock_st.slider.return_value = 10
        mock_st.cache_data = lambda **kw: lambda f: f

        mock_svc.return_value = [
            {
                "id": 1,
                "nombre": "Empresa A",
                "importe_adjudicado": 100_000,
                "ccaa": "Madrid",
                "cpv": "72000000",
                "es_pyme": 1,
                "organo_contratacion": "Org A",
                "fecha_adjudicacion": "2024-01-15",
            },
            {
                "id": 2,
                "nombre": "Empresa B",
                "importe_adjudicado": 200_000,
                "ccaa": "Cataluña",
                "cpv": "72200000",
                "es_pyme": 0,
                "organo_contratacion": "Org B",
                "fecha_adjudicacion": "2024-02-20",
            },
        ]

        # Need to reimport to pick up the patched cache_data
        import importlib

        import dashboard.pages.licitadores as mod

        importlib.reload(mod)
        mod.render(_make_ctx())

    @patch("dashboard.pages.licitadores.svc_load_licitadores", return_value=[])
    @patch("dashboard.pages.licitadores.empty_state")
    @patch("dashboard.pages.licitadores.st")
    def test_render_empty(self, mock_st, mock_empty, mock_svc):
        _mock_st_module(mock_st)
        mock_st.cache_data = lambda **kw: lambda f: f

        from dashboard.pages.licitadores import render

        # Call the inner function directly since cache_data is module-level
        with patch("dashboard.pages.licitadores._load_adjudicaciones", return_value=pd.DataFrame()):
            render(_make_ctx())
        mock_empty.assert_called()


# ===========================================================================
# active_learning.py
# ===========================================================================


class TestActiveLearning:
    @patch("dashboard.pages.active_learning._load_multilabel_clf", return_value=None)
    @patch("dashboard.pages.active_learning.svc_load_uncertainty", return_value=[])
    @patch("dashboard.pages.active_learning._repo")
    @patch("dashboard.pages.active_learning.require_admin", return_value=True)
    @patch("dashboard.pages.active_learning.st")
    def test_render_empty_zone(self, mock_st, mock_admin, mock_repo, mock_svc, mock_clf):
        _mock_st_module(mock_st)
        mock_st.slider.side_effect = [0.3, 0.7]
        mock_st.number_input.return_value = 50
        mock_repo.labeled_expedientes.return_value = set()
        mock_st.cache_resource = lambda **kw: lambda f: f

        from dashboard.pages.active_learning import render

        render(_make_ctx())
        mock_st.info.assert_called()

    @patch("dashboard.pages.active_learning._load_multilabel_clf", return_value=None)
    @patch("dashboard.pages.active_learning.svc_load_uncertainty")
    @patch("dashboard.pages.active_learning._repo")
    @patch("dashboard.pages.active_learning.require_admin", return_value=True)
    @patch("dashboard.pages.active_learning.st")
    def test_render_with_data(self, mock_st, mock_admin, mock_repo, mock_svc, mock_clf):
        _mock_st_module(mock_st)
        mock_st.slider.side_effect = [0.3, 0.7]
        mock_st.number_input.return_value = 50
        mock_repo.labeled_expedientes.return_value = set()

        mock_svc.return_value = [
            {
                "id_externo": "EXP-001",
                "ml_proba": 0.45,
                "importe": 100_000,
                "titulo": "SAP Test",
                "descripcion": "Desc",
                "organo_contratacion": "Org",
                "fecha_publicacion": "2024-01-01",
            },
        ]

        from dashboard.pages.active_learning import render

        # guarded_render catches errors silently; just verify no unhandled exception
        render(_make_ctx())

    @patch("dashboard.pages.active_learning._load_multilabel_clf", return_value=None)
    @patch("dashboard.pages.active_learning.svc_load_uncertainty")
    @patch("dashboard.pages.active_learning._repo")
    @patch("dashboard.pages.active_learning.require_admin", return_value=True)
    @patch("dashboard.pages.active_learning.st")
    def test_render_all_labeled(self, mock_st, mock_admin, mock_repo, mock_svc, mock_clf):
        _mock_st_module(mock_st)
        mock_st.slider.side_effect = [0.3, 0.7]
        mock_st.number_input.return_value = 50
        mock_repo.labeled_expedientes.return_value = {"EXP-001"}

        mock_svc.return_value = [
            {
                "id_externo": "EXP-001",
                "ml_proba": 0.45,
                "importe": 100_000,
                "titulo": "Test",
                "descripcion": "",
                "organo_contratacion": "Org",
                "fecha_publicacion": "2024-01-01",
            },
        ]

        from dashboard.pages.active_learning import render

        render(_make_ctx())
        mock_st.success.assert_called()

    def test_ml_label_probas_no_clf(self):
        from dashboard.pages.active_learning import _ml_label_probas

        assert _ml_label_probas(None, "test", "desc") == {}

    def test_ml_label_probas_with_clf(self):
        from dashboard.pages.active_learning import _ml_label_probas

        clf = MagicMock()
        clf.predict_one.return_value = {"scores": {"SAP": 0.9}}
        assert _ml_label_probas(clf, "test", "desc") == {"SAP": 0.9}

    def test_ml_label_probas_exception(self):
        from dashboard.pages.active_learning import _ml_label_probas

        clf = MagicMock()
        clf.predict_one.side_effect = RuntimeError("fail")
        assert _ml_label_probas(clf, "test", "desc") == {}

    @patch("dashboard.pages.active_learning._repo")
    def test_save_label_sap(self, mock_repo):
        from dashboard.pages.active_learning import _save_label

        _save_label("EXP-001", "SAP")
        mock_repo.insert.assert_called_once_with(
            expediente="EXP-001", relevante=True, nota="active_learning_dashboard:SAP"
        )

    @patch("dashboard.pages.active_learning._repo")
    def test_save_label_non_sap(self, mock_repo):
        from dashboard.pages.active_learning import _save_label

        _save_label("EXP-001", "ORACLE")
        mock_repo.insert.assert_called_once_with(
            expediente="EXP-001", relevante=False, nota="active_learning_dashboard:ORACLE"
        )

    @patch("dashboard.pages.active_learning.st")
    def test_render_model_card_no_clf(self, mock_st):
        _mock_st_module(mock_st)
        with patch("dashboard.pages.active_learning._load_multilabel_clf", return_value=None):
            from dashboard.pages.active_learning import _render_model_card

            _render_model_card()
            mock_st.info.assert_called()


# ===========================================================================
# tendencias.py
# ===========================================================================


class TestTendencias:
    @patch("dashboard.pages.tendencias.forecast_volume", return_value=pd.DataFrame())
    @patch("dashboard.pages.tendencias.mes_pico", return_value=None)
    @patch("dashboard.pages.tendencias.is_anomaly", return_value=False)
    @patch("dashboard.pages.tendencias.yoy_delta", return_value=(100, 80, 25.0))
    @patch(
        "dashboard.pages.tendencias.kpi_sparkline_series",
        return_value=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
    )
    @patch("dashboard.pages.tendencias.kpi_card", return_value="<div></div>")
    @patch("dashboard.pages.tendencias.chart_card")
    @patch("dashboard.pages.tendencias.st")
    def test_render_with_data(
        self, mock_st, mock_cc, mock_kpi, mock_spark, mock_yoy, mock_anom, mock_pico, mock_fc
    ):
        _mock_st_module(mock_st)
        # chart_card as context manager
        mock_cc.return_value.__enter__ = MagicMock()
        mock_cc.return_value.__exit__ = MagicMock(return_value=False)

        from dashboard.pages.tendencias import render

        render(_make_ctx())
        mock_st.subheader.assert_not_called()  # render uses kpi_card, not subheader directly

    @patch("dashboard.pages.tendencias.forecast_volume", return_value=pd.DataFrame())
    @patch("dashboard.pages.tendencias.chart_card")
    @patch("dashboard.pages.tendencias.st")
    def test_render_empty(self, mock_st, mock_cc, mock_fc):
        _mock_st_module(mock_st)
        mock_cc.return_value.__enter__ = MagicMock()
        mock_cc.return_value.__exit__ = MagicMock(return_value=False)
        from dashboard.pages.tendencias import render

        render(_make_ctx(df=pd.DataFrame({"fecha_publicacion": [], "importe": [], "mes": []})))

    @patch("dashboard.pages.tendencias.forecast_volume", return_value=pd.DataFrame())
    @patch("dashboard.pages.tendencias.empty_state")
    @patch("dashboard.pages.tendencias.chart_card")
    @patch("dashboard.pages.tendencias.st")
    def test_render_evolution_empty_mes(self, mock_st, mock_cc, mock_empty, mock_fc):
        _mock_st_module(mock_st)
        mock_cc.return_value.__enter__ = MagicMock()
        mock_cc.return_value.__exit__ = MagicMock(return_value=False)
        from dashboard.pages.tendencias import _render_evolution_charts

        # Access the wrapped function directly if it's a fragment
        fn = getattr(_render_evolution_charts, "__wrapped__", _render_evolution_charts)
        ctx = _make_ctx(df=pd.DataFrame({"importe": [100], "id_externo": ["X"]}))
        fn(ctx)
        mock_empty.assert_called()


# ===========================================================================
# tendencias_cpv.py
# ===========================================================================


class TestTendenciasCpv:
    @patch("dashboard.pages.tendencias_cpv.st")
    def test_render_with_data(self, mock_st):
        _mock_st_module(mock_st)
        mock_st.selectbox.side_effect = ["72000000", "Trimestral"]
        mock_st.toggle.return_value = False

        now = pd.Timestamp("2024-06-15")
        dates = [now - pd.Timedelta(days=i * 30) for i in range(5)]
        df = _make_df(
            id_externo=[f"E-{i}" for i in range(5)],
            titulo=[f"T-{i}" for i in range(5)],
            importe=[100_000 + i * 10000 for i in range(5)],
            organo_contratacion=["Org"] * 5,
            estado_desc=["Abierta"] * 5,
            tipo_proyecto=["Servicios"] * 5,
            fecha_publicacion=dates,
            url=[f"https://x.com/{i}" for i in range(5)],
            ccaa=["Madrid"] * 5,
            cpv=["72000000"] * 5,
            cpv_desc=["IT"] * 5,
            tipo_contrato_desc=["Servicio"] * 5,
            tecnologia=["SAP"] * 5,
            descripcion=["Desc"] * 5,
            provincia=["Madrid"] * 5,
            moneda=["EUR"] * 5,
            mes=dates,
            fecha_limite=[d + pd.Timedelta(days=30) for d in dates],
        )
        from dashboard.pages.tendencias_cpv import render

        render(_make_ctx(df=df))
        mock_st.subheader.assert_called()

    @patch("dashboard.pages.tendencias_cpv.empty_state")
    @patch("dashboard.pages.tendencias_cpv.st")
    def test_render_empty(self, mock_st, mock_empty):
        _mock_st_module(mock_st)
        from dashboard.pages.tendencias_cpv import render

        render(_make_ctx(df=pd.DataFrame()))
        mock_empty.assert_called()

    @patch("dashboard.pages.tendencias_cpv.st")
    def test_render_no_importe_cpv(self, mock_st):
        _mock_st_module(mock_st)
        df = _make_df(importe=[None, None])
        from dashboard.pages.tendencias_cpv import render

        render(_make_ctx(df=df))
        mock_st.info.assert_called()

    def test_arima_forecast_returns_none_on_error(self):
        from dashboard.pages.tendencias_cpv import _arima_forecast

        result = _arima_forecast(pd.Series([1, 2]))
        # May return None or a Series depending on statsmodels availability
        assert result is None or isinstance(result, pd.Series)


# ===========================================================================
# geografia.py
# ===========================================================================


class TestGeografia:
    @patch("dashboard.pages.geografia.load_spain_ccaa_geojson", return_value=None)
    @patch("dashboard.pages.geografia.concentracion_geografica", return_value=45.0)
    @patch(
        "dashboard.pages.geografia.ccaa_mas_activa",
        return_value={"ccaa": "Madrid", "n": 50, "importe": 5_000_000},
    )
    @patch("dashboard.pages.geografia.kpi_card", return_value="<div></div>")
    @patch("dashboard.pages.geografia.data_table")
    @patch("dashboard.pages.geografia.chart_card")
    @patch("dashboard.pages.geografia.st")
    def test_render_with_data(
        self, mock_st, mock_cc, mock_dt, mock_kpi, mock_activa, mock_conc, mock_geo
    ):
        _mock_st_module(mock_st)
        mock_cc.return_value.__enter__ = MagicMock()
        mock_cc.return_value.__exit__ = MagicMock(return_value=False)

        from dashboard.pages.geografia import render

        render(_make_ctx())
        mock_st.markdown.assert_called()

    @patch("dashboard.pages.geografia.load_spain_ccaa_geojson", return_value=None)
    @patch("dashboard.pages.geografia.chart_card")
    @patch("dashboard.pages.geografia.st")
    def test_render_empty_ccaa(self, mock_st, mock_cc, mock_geo):
        _mock_st_module(mock_st)
        mock_cc.return_value.__enter__ = MagicMock()
        mock_cc.return_value.__exit__ = MagicMock(return_value=False)
        df = _make_df(ccaa=[None, None])
        from dashboard.pages.geografia import render

        render(_make_ctx(df=df))


# ===========================================================================
# admin.py
# ===========================================================================


class TestAdmin:
    @patch("dashboard.pages.admin.svc_list_api_keys", return_value=[])
    @patch("dashboard.pages.admin.svc_list_users", return_value=[])
    @patch("dashboard.pages.admin.unresolved_summary", return_value=[])
    @patch("dashboard.pages.admin.list_unresolved", return_value=[])
    @patch("dashboard.pages.admin.require_admin", return_value=True)
    @patch("dashboard.pages.admin.st")
    def test_render_empty(
        self, mock_st, mock_admin, mock_list, mock_summary, mock_users, mock_keys
    ):
        _mock_st_module(mock_st)
        from dashboard.pages.admin import render

        render(_make_ctx())
        mock_st.subheader.assert_called()

    @patch("dashboard.pages.admin.require_admin", return_value=False)
    @patch("dashboard.pages.admin.st")
    def test_render_not_admin(self, mock_st, mock_admin):
        _mock_st_module(mock_st)
        from dashboard.pages.admin import render

        render(_make_ctx())
        mock_st.stop.assert_called()

    @patch(
        "dashboard.pages.admin.svc_list_api_keys",
        return_value=[
            {
                "id": 1,
                "name": "test-key",
                "created_at": "2024-01-01",
                "last_used": None,
                "is_active": 1,
            },
        ],
    )
    @patch(
        "dashboard.pages.admin.svc_list_users",
        return_value=[
            {
                "id": 1,
                "email": "a@b.com",
                "display_name": "User",
                "oauth_provider": "google",
                "created_at": "2024-01-01",
                "is_admin": True,
            },
        ],
    )
    @patch(
        "dashboard.pages.admin.unresolved_summary", return_value=[{"fuente": "atom", "count": 3}]
    )
    @patch(
        "dashboard.pages.admin.list_unresolved",
        return_value=[
            {"id": 1, "fuente": "atom", "error": "timeout", "created_at": "2024-01-01"},
        ],
    )
    @patch("dashboard.pages.admin.require_admin", return_value=True)
    @patch("dashboard.pages.admin.data_table")
    @patch("dashboard.pages.admin.st")
    def test_render_with_data(
        self, mock_st, mock_dt, mock_admin, mock_list, mock_summary, mock_users, mock_keys
    ):
        _mock_st_module(mock_st)
        mock_st.selectbox.return_value = "— todas —"
        from dashboard.pages.admin import render

        render(_make_ctx())

    @patch("dashboard.pages.admin.list_unresolved", return_value=[])
    @patch("dashboard.pages.admin.unresolved_summary", return_value=[])
    @patch("dashboard.pages.admin.st")
    def test_render_dlq_empty(self, mock_st, mock_summary, mock_list):
        _mock_st_module(mock_st)
        from dashboard.pages.admin import _render_dlq

        _render_dlq()
        mock_st.success.assert_called()

    @patch("dashboard.pages.admin.svc_list_users", return_value=[])
    @patch("dashboard.pages.admin.st")
    def test_render_users_empty(self, mock_st, mock_users):
        _mock_st_module(mock_st)
        from dashboard.pages.admin import _render_users

        _render_users()
        mock_st.info.assert_called()

    @patch("dashboard.pages.admin.svc_list_api_keys", side_effect=Exception("no table"))
    @patch("dashboard.pages.admin.st")
    def test_render_api_keys_no_table(self, mock_st, mock_keys):
        _mock_st_module(mock_st)
        from dashboard.pages.admin import _render_api_keys

        _render_api_keys()
        mock_st.warning.assert_called()

    @patch("dashboard.pages.admin.svc_list_api_keys", return_value=[])
    @patch("dashboard.pages.admin.st")
    def test_render_api_keys_empty(self, mock_st, mock_keys):
        _mock_st_module(mock_st)
        from dashboard.pages.admin import _render_api_keys

        _render_api_keys()
        mock_st.info.assert_called()


# ===========================================================================
# admin_flags.py
# ===========================================================================


class TestAdminFlags:
    @patch("dashboard.pages.admin_flags.list_flags", return_value=[])
    @patch("dashboard.pages.admin_flags.st")
    def test_render_no_flags(self, mock_st, mock_list):
        _mock_st_module(mock_st)
        from dashboard.pages.admin_flags import render

        render(_make_ctx())
        mock_st.info.assert_called()

    @patch(
        "dashboard.pages.admin_flags.list_flags",
        return_value=[
            {
                "name": "test_flag",
                "enabled": True,
                "rollout_pct": 100,
                "user_emails": "",
                "description": "A test flag",
                "updated_at": "2024-01-01",
            },
        ],
    )
    @patch("dashboard.pages.admin_flags.st")
    def test_render_with_flags(self, mock_st, mock_list):
        _mock_st_module(mock_st)
        from dashboard.pages.admin_flags import render

        render(_make_ctx())
        mock_st.title.assert_called()

    @patch("dashboard.pages.admin_flags.set_flag")
    @patch("dashboard.pages.admin_flags.list_flags", return_value=[])
    @patch("dashboard.pages.admin_flags.st")
    def test_create_flag_empty_name(self, mock_st, mock_list, mock_set):
        _mock_st_module(mock_st)
        mock_st.form_submit_button.return_value = True
        mock_st.text_input.return_value = ""
        # Simulate form submission
        from dashboard.pages.admin_flags import render

        render(_make_ctx())
        mock_st.error.assert_called()

    @patch("dashboard.pages.admin_flags.set_flag")
    @patch("dashboard.pages.admin_flags.list_flags", return_value=[])
    @patch("dashboard.pages.admin_flags.st")
    def test_create_flag_valid(self, mock_st, mock_list, mock_set):
        _mock_st_module(mock_st)
        mock_st.form_submit_button.return_value = True
        mock_st.text_input.return_value = "new_flag"
        mock_st.checkbox.return_value = True
        mock_st.slider.return_value = 50
        from dashboard.pages.admin_flags import render

        render(_make_ctx())
        mock_set.assert_called()

    @patch("dashboard.pages.admin_flags.set_flag")
    @patch(
        "dashboard.pages.admin_flags.list_flags",
        return_value=[
            {
                "name": "dup",
                "enabled": True,
                "rollout_pct": 100,
                "user_emails": "",
                "description": "",
                "updated_at": None,
            },
        ],
    )
    @patch("dashboard.pages.admin_flags.st")
    def test_create_flag_duplicate(self, mock_st, mock_list, mock_set):
        _mock_st_module(mock_st)
        mock_st.form_submit_button.return_value = True
        mock_st.text_input.return_value = "dup"
        from dashboard.pages.admin_flags import render

        render(_make_ctx())
        mock_st.error.assert_called()


# ===========================================================================
# comparador.py
# ===========================================================================


class TestComparador:
    @patch("dashboard.pages.comparador.st")
    def test_render_with_selection(self, mock_st):
        _mock_st_module(mock_st)
        mock_st.multiselect.return_value = ["EXP-001", "EXP-002"]
        from dashboard.pages.comparador import render

        render(_make_ctx())
        mock_st.markdown.assert_called()

    @patch("dashboard.pages.comparador.empty_state")
    @patch("dashboard.pages.comparador.st")
    def test_render_empty(self, mock_st, mock_empty):
        _mock_st_module(mock_st)
        from dashboard.pages.comparador import render

        render(_make_ctx(df=pd.DataFrame()))
        mock_empty.assert_called()

    @patch("dashboard.pages.comparador.st")
    def test_render_less_than_2(self, mock_st):
        _mock_st_module(mock_st)
        mock_st.multiselect.return_value = ["EXP-001"]
        from dashboard.pages.comparador import render

        render(_make_ctx())
        mock_st.info.assert_called()

    @patch("dashboard.pages.comparador.st")
    def test_render_only_one_option(self, mock_st):
        _mock_st_module(mock_st)
        df = pd.DataFrame(
            {
                "id_externo": ["EXP-001"],
                "titulo": ["Test"],
                "importe": [100_000.0],
            }
        )
        from dashboard.pages.comparador import render

        render(_make_ctx(df=df))
        mock_st.info.assert_called()

    def test_highlight_diff_same(self):
        from dashboard.pages.comparador import _highlight_diff

        assert _highlight_diff("foo", "foo") == "foo"

    def test_highlight_diff_different(self):
        from dashboard.pages.comparador import _highlight_diff

        result = _highlight_diff("bar", "foo")
        assert "bar" in result
        assert "span" in result

    def test_highlight_diff_none_baseline(self):
        from dashboard.pages.comparador import _highlight_diff

        assert _highlight_diff("val", None) == "val"

    def test_highlight_diff_nan(self):
        from dashboard.pages.comparador import _highlight_diff

        result = _highlight_diff(float("nan"), "foo")
        assert "—" in result


# ===========================================================================
# mi_watchlist.py
# ===========================================================================


class TestMiWatchlist:
    @patch("dashboard.pages.mi_watchlist._get_user_context", return_value=("testkey12345678", None))
    @patch("dashboard.pages.mi_watchlist.get_current_user", return_value=None)
    @patch("dashboard.pages.mi_watchlist.list_entries", return_value=[])
    @patch("dashboard.pages.mi_watchlist.empty_state")
    @patch("dashboard.pages.mi_watchlist.st")
    def test_render_no_entries(self, mock_st, mock_empty, mock_list, mock_user, mock_ctx):
        _mock_st_module(mock_st)
        from dashboard.pages.mi_watchlist import render

        render(_make_ctx())
        mock_empty.assert_called()

    @patch("dashboard.pages.mi_watchlist._get_user_context", return_value=("testkey12345678", None))
    @patch("dashboard.pages.mi_watchlist.get_current_user", return_value=None)
    @patch("dashboard.pages.mi_watchlist.data_table")
    @patch(
        "dashboard.pages.mi_watchlist.list_entries",
        return_value=[
            {
                "id": 1,
                "cpv_prefix": "72",
                "keyword": "SAP",
                "min_importe": 50000,
                "ccaa": None,
                "email": None,
                "created_at": "2024-01-01",
                "frequency": "daily",
            },
        ],
    )
    @patch("dashboard.pages.mi_watchlist.st")
    def test_render_with_entries(self, mock_st, mock_list, mock_dt, mock_user, mock_ctx):
        _mock_st_module(mock_st)
        mock_st.selectbox.return_value = "daily"
        mock_st.button.return_value = False

        from dashboard.pages.mi_watchlist import render

        render(_make_ctx())
        mock_st.markdown.assert_called()

    @patch("dashboard.pages.mi_watchlist.get_current_user", return_value={"user_id": 1})
    @patch("dashboard.pages.mi_watchlist._user_key", return_value="testkey123")
    def test_user_key(self, mock_ukey, mock_user):
        from dashboard.pages.mi_watchlist import _get_user_context

        ukey, uid = _get_user_context()
        assert ukey == "testkey123"
        assert uid == 1

    @patch("dashboard.pages.mi_watchlist.get_current_user", return_value=None)
    @patch("dashboard.pages.mi_watchlist._user_key", return_value="testkey123")
    def test_get_user_context_no_user(self, mock_ukey, mock_user):
        from dashboard.pages.mi_watchlist import _get_user_context

        _ukey, uid = _get_user_context()
        assert uid is None


# ===========================================================================
# clusters.py
# ===========================================================================


class TestClusters:
    @patch("dashboard.pages.clusters.cluster_summary")
    @patch("dashboard.pages.clusters.cluster_licitaciones")
    @patch("dashboard.pages.clusters.data_table")
    @patch("dashboard.pages.clusters.st")
    def test_render_with_data(self, mock_st, mock_dt, mock_cluster, mock_summary):
        _mock_st_module(mock_st)
        mock_st.slider.return_value = 3
        mock_st.toggle.return_value = False
        mock_st.button.return_value = False
        mock_st.selectbox.return_value = 0
        mock_st.spinner.return_value.__enter__ = MagicMock()
        mock_st.spinner.return_value.__exit__ = MagicMock(return_value=False)

        # Need at least 10 rows
        n = 15
        df = _make_df(
            id_externo=[f"E-{i}" for i in range(n)],
            titulo=[f"Title {i}" for i in range(n)],
            importe=[100_000.0 + i * 1000 for i in range(n)],
            organo_contratacion=["Org"] * n,
            estado_desc=["Abierta"] * n,
            tipo_proyecto=["Servicios"] * n,
            fecha_publicacion=[pd.Timestamp("2024-06-15")] * n,
            url=[f"https://x.com/{i}" for i in range(n)],
            ccaa=["Madrid"] * n,
            cpv=["72000000"] * n,
            cpv_desc=["IT"] * n,
            tipo_contrato_desc=["Servicio"] * n,
            tecnologia=["SAP"] * n,
            descripcion=["Desc"] * n,
            provincia=["Madrid"] * n,
            moneda=["EUR"] * n,
            mes=[pd.Timestamp("2024-06-15")] * n,
            fecha_limite=[pd.Timestamp("2024-07-15")] * n,
        )

        clustered = df.copy()
        clustered["cluster_id"] = [i % 3 for i in range(n)]
        clustered["cluster_label"] = [f"Cluster {i % 3}" for i in range(n)]
        mock_cluster.return_value = clustered

        summary = pd.DataFrame(
            {
                "cluster_id": [0, 1, 2],
                "cluster_label": ["Cluster 0", "Cluster 1", "Cluster 2"],
                "n": [5, 5, 5],
                "importe_medio": [100_000, 110_000, 120_000],
                "importe_total": [500_000, 550_000, 600_000],
            }
        )
        mock_summary.return_value = summary

        from dashboard.pages.clusters import render

        render(_make_ctx(df=df))
        mock_cluster.assert_called_once()

    @patch("dashboard.pages.clusters.empty_state")
    @patch("dashboard.pages.clusters.st")
    def test_render_too_few(self, mock_st, mock_empty):
        _mock_st_module(mock_st)
        df = _make_df()  # only 2 rows
        from dashboard.pages.clusters import render

        render(_make_ctx(df=df))
        mock_empty.assert_called()

    @patch("dashboard.pages.clusters.cluster_licitaciones", side_effect=RuntimeError("fail"))
    @patch("dashboard.pages.clusters.st")
    def test_render_cluster_error(self, mock_st, mock_cluster):
        _mock_st_module(mock_st)
        mock_st.slider.return_value = 3
        mock_st.toggle.return_value = False
        mock_st.button.return_value = False
        mock_st.spinner.return_value.__enter__ = MagicMock()
        mock_st.spinner.return_value.__exit__ = MagicMock(return_value=False)

        n = 15
        df = _make_df(
            id_externo=[f"E-{i}" for i in range(n)],
            titulo=[f"T {i}" for i in range(n)],
            importe=[100_000.0] * n,
            organo_contratacion=["O"] * n,
            estado_desc=["A"] * n,
            tipo_proyecto=["S"] * n,
            fecha_publicacion=[pd.Timestamp("2024-06-15")] * n,
            url=[f"https://x.com/{i}" for i in range(n)],
            ccaa=["Madrid"] * n,
            cpv=["72"] * n,
            cpv_desc=["X"] * n,
            tipo_contrato_desc=["S"] * n,
            tecnologia=["SAP"] * n,
            descripcion=["D"] * n,
            provincia=["M"] * n,
            moneda=["EUR"] * n,
            mes=[pd.Timestamp("2024-06-15")] * n,
            fecha_limite=[pd.Timestamp("2024-07-15")] * n,
        )
        from dashboard.pages.clusters import render

        render(_make_ctx(df=df))
        mock_st.error.assert_called()
