"""Unit tests for dashboard pages: resumen, investigador, detalle."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from dashboard.filters.state import FiltersState
from dashboard.pages._base import PageContext

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_df(n=5, with_adj_cols=False):
    """Create a sample DataFrame mimicking licitaciones."""
    now = pd.Timestamp.now("UTC")
    data = {
        "id_externo": [f"EXP-{i}" for i in range(n)],
        "titulo": [f"Licitación {i}" for i in range(n)],
        "importe": [100000.0 * (i + 1) for i in range(n)],
        "estado_desc": ["Adjudicada"] * n,
        "tipo_proyecto": ["Servicios"] * n,
        "organo_contratacion": ["Ministerio X"] * n,
        "fecha_publicacion": pd.date_range(
            now - pd.Timedelta(days=n), periods=n, freq="D", tz="UTC"
        ),
        "url": [f"https://example.com/{i}" for i in range(n)],
        "modulos_str": ["SAP FI"] * n,
        "ccaa": ["Madrid"] * n,
        "cpv_desc": ["72000000"] * n,
        "descripcion": ["Desc test"] * n,
        "tipo_contrato_desc": ["Servicios"] * n,
        "provincia": ["Madrid"] * n,
        "tecnologia": ["SAP"] * n,
    }
    if with_adj_cols:
        data["licitacion_id"] = data["id_externo"]
        data["nombre_canonico"] = ["Empresa A"] * n
        data["baja_pct"] = [10.0] * n
        data["fecha_adjudicacion"] = data["fecha_publicacion"]
        data["importe_adjudicado"] = data["importe"]
        data["es_pyme"] = [1] * n
        data["n_ofertas_recibidas"] = [3] * n
    return pd.DataFrame(data)


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
        color_sequence=["#86BC24"],
    )


def _mock_st(mock_st_obj):
    """Configure common st mock attributes."""
    mock_st_obj.session_state = {}
    mock_st_obj.columns.return_value = [
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    ]
    mock_st_obj.expander.return_value.__enter__ = MagicMock()
    mock_st_obj.expander.return_value.__exit__ = MagicMock(return_value=False)
    mock_st_obj.empty.return_value = MagicMock()
    mock_st_obj.query_params = {}
    mock_st_obj.column_config = MagicMock()


# ══════════════════════════════════════════════════════════════════════════════
# RESUMEN
# ══════════════════════════════════════════════════════════════════════════════


class TestResumenRenderTopLicitaciones:
    @patch("dashboard.pages.resumen.top_card")
    @patch("dashboard.pages.resumen.st")
    def test_empty_df(self, mock_st, mock_top_card):
        _mock_st(mock_st)
        from dashboard.pages.resumen import _render_top_licitaciones

        df = pd.DataFrame(columns=["importe", "titulo"])
        adj = pd.DataFrame()
        _render_top_licitaciones.__wrapped__(df, adj)
        mock_top_card.assert_not_called()

    @patch("dashboard.pages.resumen.fmt_eur", return_value="100.000 €")
    @patch("dashboard.pages.resumen.top_card")
    @patch("dashboard.pages.resumen.st")
    def test_with_data(self, mock_st, mock_top_card, mock_fmt):
        _mock_st(mock_st)
        from dashboard.pages.resumen import _render_top_licitaciones

        df = _make_df(3)
        adj = pd.DataFrame()
        _render_top_licitaciones.__wrapped__(df, adj)
        assert mock_top_card.call_count == 3

    @patch("dashboard.pages.resumen.fmt_eur", return_value="100.000 €")
    @patch("dashboard.pages.resumen.top_card")
    @patch("dashboard.pages.resumen.st")
    def test_with_adjudicaciones(self, mock_st, mock_top_card, mock_fmt):
        _mock_st(mock_st)
        from dashboard.pages.resumen import _render_top_licitaciones

        df = _make_df(2)
        adj = _make_df(2, with_adj_cols=True)
        _render_top_licitaciones.__wrapped__(df, adj)
        assert mock_top_card.call_count == 2

    @patch("dashboard.pages.resumen.fmt_eur", return_value="100.000 €")
    @patch("dashboard.pages.resumen.top_card")
    @patch("dashboard.pages.resumen.st")
    def test_no_importe_column(self, mock_st, mock_top_card, mock_fmt):
        _mock_st(mock_st)
        from dashboard.pages.resumen import _render_top_licitaciones

        df = pd.DataFrame({"titulo": ["A"]})
        _render_top_licitaciones.__wrapped__(df, pd.DataFrame())
        mock_top_card.assert_not_called()


class TestResumenRender:
    @patch("dashboard.pages.resumen.lazy_section")
    @patch("dashboard.pages.resumen._render_actividad_reciente")
    @patch("dashboard.pages.resumen._render_timeline")
    @patch("dashboard.pages.resumen._render_banner_hoy")
    @patch("dashboard.pages.resumen._render_top_licitaciones")
    @patch("dashboard.pages.resumen.chart_card")
    @patch("dashboard.pages.resumen.load_adjudicaciones")
    @patch("dashboard.pages.resumen.px")
    @patch("dashboard.pages.resumen.st")
    def test_render_basic(
        self,
        mock_st,
        mock_px,
        mock_load_adj,
        mock_chart,
        mock_top,
        mock_banner,
        mock_timeline,
        mock_actividad,
        mock_lazy,
    ):
        _mock_st(mock_st)
        mock_load_adj.return_value = pd.DataFrame()
        mock_chart.return_value.__enter__ = MagicMock()
        mock_chart.return_value.__exit__ = MagicMock(return_value=False)
        mock_lazy.return_value.__enter__ = MagicMock(return_value=False)
        mock_lazy.return_value.__exit__ = MagicMock(return_value=False)
        col_mock = MagicMock()
        col_mock.__enter__ = MagicMock(return_value=col_mock)
        col_mock.__exit__ = MagicMock(return_value=False)
        mock_st.columns.return_value = [col_mock, col_mock]

        ctx = _make_ctx()
        from dashboard.pages.resumen import render

        render.__wrapped__(ctx)

        mock_load_adj.assert_called_once()
        mock_banner.assert_called_once()
        mock_timeline.assert_called_once()
        mock_actividad.assert_called_once()

    @patch("dashboard.pages.resumen.lazy_section")
    @patch("dashboard.pages.resumen._render_actividad_reciente")
    @patch("dashboard.pages.resumen._render_timeline")
    @patch("dashboard.pages.resumen._render_banner_hoy")
    @patch("dashboard.pages.resumen._render_top_licitaciones")
    @patch("dashboard.pages.resumen.chart_card")
    @patch("dashboard.pages.resumen.load_adjudicaciones")
    @patch("dashboard.pages.resumen.px")
    @patch("dashboard.pages.resumen.st")
    def test_render_with_last_visit(
        self,
        mock_st,
        mock_px,
        mock_load_adj,
        mock_chart,
        mock_top,
        mock_banner,
        mock_timeline,
        mock_actividad,
        mock_lazy,
    ):
        _mock_st(mock_st)
        from dashboard.pages.resumen import LAST_VISIT_TS

        mock_st.session_state[LAST_VISIT_TS] = pd.Timestamp("2020-01-01", tz="UTC")
        mock_load_adj.return_value = pd.DataFrame()
        mock_chart.return_value.__enter__ = MagicMock()
        mock_chart.return_value.__exit__ = MagicMock(return_value=False)
        mock_lazy.return_value.__enter__ = MagicMock(return_value=False)
        mock_lazy.return_value.__exit__ = MagicMock(return_value=False)
        col_mock = MagicMock()
        col_mock.__enter__ = MagicMock(return_value=col_mock)
        col_mock.__exit__ = MagicMock(return_value=False)
        mock_st.columns.return_value = [col_mock, col_mock]
        exp_mock = MagicMock()
        exp_mock.__enter__ = MagicMock()
        exp_mock.__exit__ = MagicMock(return_value=False)
        mock_st.expander.return_value = exp_mock

        ctx = _make_ctx()
        from dashboard.pages.resumen import render

        render.__wrapped__(ctx)

        # Should have called expander for new licitaciones
        mock_st.expander.assert_called()


class TestResumenRenderTimeline:
    @patch("dashboard.pages.resumen.safe_url", return_value=None)
    @patch("dashboard.pages.resumen.fmt_eur", return_value="100 €")
    @patch("dashboard.pages.resumen.chart_card")
    @patch("dashboard.pages.resumen.px")
    @patch("dashboard.pages.resumen.st")
    def test_empty_df(self, mock_st, mock_px, mock_chart, mock_fmt, mock_safe):
        _mock_st(mock_st)
        from dashboard.pages.resumen import _render_timeline

        _render_timeline(pd.DataFrame(columns=["fecha_publicacion"]), _make_ctx())
        mock_st.plotly_chart.assert_not_called()

    @patch("dashboard.pages.resumen.safe_url", return_value=None)
    @patch("dashboard.pages.resumen.fmt_eur", return_value="100 €")
    @patch("dashboard.pages.resumen.chart_card")
    @patch("dashboard.pages.resumen.px")
    @patch("dashboard.pages.resumen.st")
    def test_no_recent(self, mock_st, mock_px, mock_chart, mock_fmt, mock_safe):
        _mock_st(mock_st)
        from dashboard.pages.resumen import _render_timeline

        df = _make_df(1)
        df["fecha_publicacion"] = pd.Timestamp("2020-01-01", tz="UTC")
        _render_timeline(df, _make_ctx(df=df))
        mock_st.info.assert_called()


class TestResumenBannerHoy:
    @patch("dashboard.pages.resumen.kpi_card", return_value="<div></div>")
    @patch("dashboard.pages.resumen.kpi_sparkline_series", return_value=[1, 2, 3])
    @patch("dashboard.pages.resumen.is_anomaly", return_value=False)
    @patch("dashboard.pages.resumen.yoy_delta", return_value=(0, 0, 0))
    @patch("dashboard.pages.resumen.calientes_hoy", return_value=[])
    @patch("dashboard.pages.resumen.vencen_en", return_value=3)
    @patch("dashboard.pages.resumen.st")
    def test_banner_renders(
        self, mock_st, mock_vencen, mock_calientes, mock_yoy, mock_anomaly, mock_spark, mock_kpi
    ):
        _mock_st(mock_st)
        col_mock = MagicMock()
        col_mock.__enter__ = MagicMock(return_value=col_mock)
        col_mock.__exit__ = MagicMock(return_value=False)
        mock_st.columns.return_value = [col_mock, col_mock, col_mock, col_mock]

        from dashboard.pages.resumen import _render_banner_hoy

        _render_banner_hoy(_make_df(), pd.DataFrame())
        assert mock_st.markdown.call_count >= 4

    @patch("dashboard.pages.resumen.st")
    def test_banner_empty_df(self, mock_st):
        _mock_st(mock_st)
        from dashboard.pages.resumen import _render_banner_hoy

        _render_banner_hoy(pd.DataFrame(), pd.DataFrame())
        mock_st.subheader.assert_not_called()


class TestResumenLicitacionDetalle:
    @patch("dashboard.pages.resumen.safe_url", return_value="https://example.com")
    @patch("dashboard.pages.resumen.fmt_eur", return_value="100 €")
    @patch("dashboard.pages.resumen.st")
    def test_renders_detail(self, mock_st, mock_fmt, mock_safe):
        _mock_st(mock_st)
        col_mock = MagicMock()
        col_mock.__enter__ = MagicMock(return_value=col_mock)
        col_mock.__exit__ = MagicMock(return_value=False)
        mock_st.columns.return_value = [col_mock, col_mock, col_mock]
        exp_mock = MagicMock()
        exp_mock.__enter__ = MagicMock()
        exp_mock.__exit__ = MagicMock(return_value=False)
        mock_st.expander.return_value = exp_mock

        row = _make_df(1).iloc[0]
        from dashboard.pages.resumen import _render_licitacion_detalle

        _render_licitacion_detalle(row)
        mock_st.metric.assert_called()
        mock_st.link_button.assert_called()


class TestResumenActividadReciente:
    @patch("dashboard.pages.resumen.fmt_eur", return_value="100 €")
    @patch("dashboard.pages.resumen.chart_card")
    @patch("dashboard.pages.resumen.px")
    @patch("dashboard.pages.resumen.st")
    def test_empty(self, mock_st, mock_px, mock_chart, mock_fmt):
        _mock_st(mock_st)
        from dashboard.pages.resumen import _render_actividad_reciente

        _render_actividad_reciente(pd.DataFrame(), _make_ctx())

    @patch("dashboard.pages.resumen.safe_url", return_value=None)
    @patch("dashboard.pages.resumen.fmt_eur", new=lambda x: f"{x or 0:,.0f} €")
    @patch("dashboard.pages.resumen.chart_card")
    @patch("dashboard.pages.resumen.px")
    @patch("dashboard.pages.resumen.st")
    def test_with_data(self, mock_st, mock_px, mock_chart, mock_safe):
        _mock_st(mock_st)
        mock_chart.return_value.__enter__ = MagicMock()
        mock_chart.return_value.__exit__ = MagicMock(return_value=False)
        col_mock = MagicMock()
        col_mock.__enter__ = MagicMock(return_value=col_mock)
        col_mock.__exit__ = MagicMock(return_value=False)
        mock_st.columns.side_effect = lambda *a, **kw: (
            [col_mock] * (a[0] if isinstance(a[0], int) else len(a[0]))
        )
        exp_mock = MagicMock()
        exp_mock.__enter__ = MagicMock()
        exp_mock.__exit__ = MagicMock(return_value=False)
        mock_st.expander.return_value = exp_mock

        df = _make_df(3)
        from dashboard.pages.resumen import _render_actividad_reciente

        _render_actividad_reciente(df, _make_ctx(df=df))


# ══════════════════════════════════════════════════════════════════════════════
# INVESTIGADOR
# ══════════════════════════════════════════════════════════════════════════════


class TestInvestigadorHelpers:
    def test_relevance_badge_alta(self):
        from dashboard.pages.investigador import _relevance_badge

        assert "Alta" in _relevance_badge(0.8)

    def test_relevance_badge_media(self):
        from dashboard.pages.investigador import _relevance_badge

        assert "Media" in _relevance_badge(0.5)

    def test_relevance_badge_baja(self):
        from dashboard.pages.investigador import _relevance_badge

        assert "Baja" in _relevance_badge(0.1)

    def test_escape_fts5_basic(self):
        from dashboard.pages.investigador import _escape_fts5

        result = _escape_fts5("hello world")
        assert '"hello"' in result
        assert '"world"' in result

    def test_escape_fts5_empty(self):
        from dashboard.pages.investigador import _escape_fts5

        assert _escape_fts5("") == '""'

    def test_escape_fts5_special_chars(self):
        from dashboard.pages.investigador import _escape_fts5

        result = _escape_fts5('hello* +world "test"')
        assert "*" not in result.replace('"', "")
        assert "+" not in result.replace('"', "")

    def test_context_excerpt_empty(self):
        from dashboard.pages.investigador import _context_excerpt

        assert _context_excerpt(None, ["kw"]) == ""
        assert _context_excerpt("", ["kw"]) == ""

    def test_context_excerpt_with_keyword(self):
        from dashboard.pages.investigador import _context_excerpt

        text = "A" * 100 + "KEYWORD" + "B" * 100
        result = _context_excerpt(text, ["keyword"], max_chars=50)
        assert len(result) <= 55  # +ellipsis chars

    def test_highlight(self):
        from dashboard.pages.investigador import _highlight

        result = _highlight("hello world test", ["world"])
        assert "<mark>" in result
        assert "world" in result

    def test_highlight_short_keyword_ignored(self):
        from dashboard.pages.investigador import _highlight

        result = _highlight("ab test", ["ab"])
        assert "<mark>" not in result

    def test_linkify_citations(self):
        from dashboard.pages.investigador import _linkify_citations

        docs = [{"id_externo": "EXP-001"}]
        result = _linkify_citations("See [EXP-001] for details", docs)
        assert "`EXP-001`" in result

    def test_linkify_citations_unknown(self):
        from dashboard.pages.investigador import _linkify_citations

        docs = [{"id_externo": "EXP-001"}]
        result = _linkify_citations("See [UNKNOWN-99] for details", docs)
        assert "[UNKNOWN-99]" in result


class TestInvestigadorRagQuery:
    @patch("dashboard.pages.investigador._fetch_docs")
    @patch("dashboard.pages.investigador._like_search")
    @patch("dashboard.pages.investigador._fts5_search")
    @patch("dashboard.pages.investigador._faiss_search")
    def test_hybrid(self, mock_faiss, mock_fts, mock_like, mock_fetch):
        mock_faiss.return_value = [("EXP-1", 0.9)]
        mock_fts.return_value = [("EXP-1", 0.8)]
        mock_fetch.return_value = {"EXP-1": {"id_externo": "EXP-1", "titulo": "T"}}
        from dashboard.pages.investigador import _rag_query

        with patch("dashboard.pages.investigador._hybrid_rerank", return_value=[("EXP-1", 0.85)]):
            docs, source = _rag_query("test", 5, None)
        assert len(docs) == 1
        assert "FAISS+FTS5" in source

    @patch("dashboard.pages.investigador._fetch_docs")
    @patch("dashboard.pages.investigador._like_search")
    @patch("dashboard.pages.investigador._fts5_search")
    @patch("dashboard.pages.investigador._faiss_search")
    def test_faiss_only(self, mock_faiss, mock_fts, mock_like, mock_fetch):
        mock_faiss.return_value = [("EXP-1", 0.9)]
        mock_fts.return_value = []
        mock_fetch.return_value = {"EXP-1": {"id_externo": "EXP-1"}}
        from dashboard.pages.investigador import _rag_query

        _docs, source = _rag_query("test", 5, None)
        assert "FAISS" in source

    @patch("dashboard.pages.investigador._fetch_docs")
    @patch("dashboard.pages.investigador._like_search")
    @patch("dashboard.pages.investigador._fts5_search")
    @patch("dashboard.pages.investigador._faiss_search")
    def test_fts_only(self, mock_faiss, mock_fts, mock_like, mock_fetch):
        mock_faiss.return_value = []
        mock_fts.return_value = [("EXP-1", 0.7)]
        mock_fetch.return_value = {"EXP-1": {"id_externo": "EXP-1"}}
        from dashboard.pages.investigador import _rag_query

        _docs, source = _rag_query("test", 5, None)
        assert "FTS5" in source

    @patch("dashboard.pages.investigador._fetch_docs")
    @patch("dashboard.pages.investigador._like_search")
    @patch("dashboard.pages.investigador._fts5_search")
    @patch("dashboard.pages.investigador._faiss_search")
    def test_like_fallback(self, mock_faiss, mock_fts, mock_like, mock_fetch):
        mock_faiss.return_value = []
        mock_fts.return_value = []
        mock_like.return_value = [("EXP-1", 0.3)]
        mock_fetch.return_value = {"EXP-1": {"id_externo": "EXP-1"}}
        from dashboard.pages.investigador import _rag_query

        _docs, source = _rag_query("test", 5, None)
        assert "LIKE" in source

    @patch("dashboard.pages.investigador._fetch_docs")
    @patch("dashboard.pages.investigador._like_search")
    @patch("dashboard.pages.investigador._fts5_search")
    @patch("dashboard.pages.investigador._faiss_search")
    def test_no_results(self, mock_faiss, mock_fts, mock_like, mock_fetch):
        mock_faiss.return_value = []
        mock_fts.return_value = []
        mock_like.return_value = []
        mock_fetch.return_value = {}
        from dashboard.pages.investigador import _rag_query

        docs, _source = _rag_query("test", 5, None)
        assert len(docs) == 0


def _inv_col_mock():
    col_mock = MagicMock()
    col_mock.__enter__ = MagicMock(return_value=col_mock)
    col_mock.__exit__ = MagicMock(return_value=False)
    col_mock.metric = MagicMock()
    col_mock.checkbox = MagicMock(return_value=False)
    return col_mock


def _setup_inv_st(mock_st, question=""):
    _mock_st(mock_st)
    mock_st.session_state = {}
    mock_st.text_area.return_value = question
    mock_st.slider.return_value = 5
    mock_st.selectbox.return_value = "gpt-4o-mini"
    mock_st.checkbox.return_value = False
    mock_st.number_input.return_value = 0
    mock_st.multiselect.return_value = []
    mock_st.button.return_value = False
    mock_st.download_button.return_value = None
    exp_mock = MagicMock()
    exp_mock.__enter__ = MagicMock()
    exp_mock.__exit__ = MagicMock(return_value=False)
    mock_st.expander.return_value = exp_mock
    col = _inv_col_mock()
    mock_st.columns.side_effect = lambda *a, **kw: (
        [col] * (a[0] if isinstance(a[0], int) else len(a[0]))
    )
    empty_mock = MagicMock()
    mock_st.empty.return_value = empty_mock
    return col


class TestInvestigadorRender:
    @patch("dashboard.pages.investigador._rag_query")
    @patch("dashboard.pages.investigador.st")
    def test_render_no_question(self, mock_st, mock_rag):
        _setup_inv_st(mock_st, "")

        with patch("dashboard.pages.investigador._EXAMPLE_QUESTIONS", ["Q1"]):
            ctx = _make_ctx()
            from dashboard.pages.investigador import render

            render.__wrapped__(ctx)

        mock_rag.assert_not_called()
        mock_st.info.assert_called()

    @patch("dashboard.pages.investigador._rag_query")
    @patch("dashboard.pages.investigador.st")
    def test_render_with_question_no_docs(self, mock_st, mock_rag):
        _setup_inv_st(mock_st, "SAP mantenimiento")
        mock_rag.return_value = ([], "⚪ LIKE")

        with patch("dashboard.pages.investigador._EXAMPLE_QUESTIONS", ["Q1"]):
            ctx = _make_ctx()
            from dashboard.pages.investigador import render

            render.__wrapped__(ctx)

        mock_st.warning.assert_called()

    @patch("dashboard.pages.investigador._rag_query")
    @patch("dashboard.pages.investigador.st")
    def test_render_with_docs_no_api_key(self, mock_st, mock_rag):
        col = _setup_inv_st(mock_st, "SAP consultoría")

        docs = [
            {
                "id_externo": "EXP-1",
                "titulo": "Test",
                "importe": 100000,
                "organo_contratacion": "Min",
                "_score": 0.8,
                "descripcion": "Desc",
                "ccaa": "Madrid",
                "estado": "Adjudicada",
                "fecha_publicacion": "2024-01-01",
                "url": "https://example.com",
            },
        ]
        mock_rag.return_value = (docs, "🟣 FAISS")

        with (
            patch("dashboard.pages.investigador._EXAMPLE_QUESTIONS", ["Q1"]),
            patch("llm.client._get_key", return_value=None),
            patch("llm.client.provider_for", return_value="openai"),
        ):
            ctx = _make_ctx()
            from dashboard.pages.investigador import render

            render.__wrapped__(ctx)

        mock_st.caption.assert_called()


# ══════════════════════════════════════════════════════════════════════════════
# DETALLE
# ══════════════════════════════════════════════════════════════════════════════


class TestDetalleRender:
    def _setup_mocks(self, mock_st):
        _mock_st(mock_st)
        col_mock = MagicMock()
        col_mock.__enter__ = MagicMock(return_value=col_mock)
        col_mock.__exit__ = MagicMock(return_value=False)
        col_mock.metric = MagicMock()
        col_mock.checkbox = MagicMock(return_value=False)
        col_mock.markdown = MagicMock()
        col_mock.download_button = MagicMock()
        mock_st.columns.side_effect = lambda *a, **kw: (
            [col_mock] * (a[0] if isinstance(a[0], int) else len(a[0]))
        )
        exp_mock = MagicMock()
        exp_mock.__enter__ = MagicMock()
        exp_mock.__exit__ = MagicMock(return_value=False)
        mock_st.expander.return_value = exp_mock
        pop_mock = MagicMock()
        pop_mock.__enter__ = MagicMock()
        pop_mock.__exit__ = MagicMock(return_value=False)
        mock_st.popover.return_value = pop_mock
        mock_st.button.return_value = False
        mock_st.multiselect.return_value = list(_get_default_cols())
        mock_st.download_button.return_value = None
        return col_mock

    @patch("dashboard.pages.detalle.timeline_popover")
    @patch("dashboard.pages.detalle.licitacion_popover")
    @patch("dashboard.pages.detalle.status_badge", return_value="<span>OK</span>")
    @patch("dashboard.pages.detalle.highlight_match", return_value="text")
    @patch("dashboard.pages.detalle.fmt_eur", return_value="100 €")
    @patch("dashboard.pages.detalle.to_excel_bytes", return_value=b"xlsx")
    @patch("dashboard.pages.detalle.to_csv_bytes", return_value=b"csv")
    @patch("dashboard.pages.detalle.paginated_df")
    @patch("dashboard.pages.detalle.data_table", return_value=None)
    @patch("dashboard.pages.detalle.reset_pagination")
    @patch("dashboard.pages.detalle.score_oportunidad")
    @patch("dashboard.pages.detalle.risk_flags")
    @patch("dashboard.pages.detalle.load_adjudicaciones")
    @patch("db.notifications.get_unread_ids", return_value=[])
    @patch("dashboard.pages.detalle._mark_read_notification")
    @patch("dashboard.pages.detalle.st")
    def test_render_basic(
        self,
        mock_st,
        mock_mark,
        mock_unread,
        mock_load_adj,
        mock_risk,
        mock_score,
        mock_reset_pg,
        mock_data_table,
        mock_paginated,
        mock_csv,
        mock_excel,
        mock_fmt,
        mock_hl,
        mock_badge,
        mock_popover,
        mock_timeline,
    ):
        col_mock = self._setup_mocks(mock_st)
        df = _make_df(2)
        adj_df = pd.DataFrame()
        mock_load_adj.return_value = adj_df

        rf_df = df[["id_externo"]].copy()
        rf_df["riesgo_flags"] = ""
        rf_df["riesgo_score"] = 0
        mock_risk.return_value = rf_df

        sc_df = df[["id_externo"]].copy()
        sc_df["score"] = 50
        sc_df["banda"] = "B"
        sc_df["desglose"] = [{}] * len(sc_df)
        mock_score.return_value = sc_df

        show = df.copy()
        show["riesgo_flags"] = ""
        show["riesgo_score"] = 0
        show["score"] = 50
        show["banda"] = "B"
        mock_paginated.return_value = (show, 1)

        ctx = _make_ctx(df=df)
        from dashboard.pages.detalle import render

        render.__wrapped__(ctx)

        mock_st.subheader.assert_called()

    @patch("dashboard.pages.detalle.timeline_popover")
    @patch("dashboard.pages.detalle.licitacion_popover")
    @patch("dashboard.pages.detalle.status_badge", return_value="<span>OK</span>")
    @patch("dashboard.pages.detalle.highlight_match", return_value="text")
    @patch("dashboard.pages.detalle.fmt_eur", return_value="100 €")
    @patch("dashboard.pages.detalle.to_excel_bytes", return_value=b"xlsx")
    @patch("dashboard.pages.detalle.to_csv_bytes", return_value=b"csv")
    @patch("dashboard.pages.detalle.paginated_df")
    @patch("dashboard.pages.detalle.data_table", return_value=None)
    @patch("dashboard.pages.detalle.reset_pagination")
    @patch("dashboard.pages.detalle.score_oportunidad")
    @patch("dashboard.pages.detalle.risk_flags")
    @patch("dashboard.pages.detalle.load_adjudicaciones")
    @patch("db.notifications.get_unread_ids", return_value=[])
    @patch("dashboard.pages.detalle._mark_read_notification")
    @patch("dashboard.pages.detalle.st")
    def test_render_scoring_failure(
        self,
        mock_st,
        mock_mark,
        mock_unread,
        mock_load_adj,
        mock_risk,
        mock_score,
        mock_reset_pg,
        mock_data_table,
        mock_paginated,
        mock_csv,
        mock_excel,
        mock_fmt,
        mock_hl,
        mock_badge,
        mock_popover,
        mock_timeline,
    ):
        col_mock = self._setup_mocks(mock_st)
        df = _make_df(1)
        mock_load_adj.return_value = pd.DataFrame()
        mock_risk.side_effect = Exception("DB error")
        mock_score.side_effect = Exception("DB error")

        show = df.copy()
        show["riesgo_flags"] = ""
        show["riesgo_score"] = 0
        show["score"] = 0
        show["banda"] = "—"
        mock_paginated.return_value = (show, 1)

        ctx = _make_ctx(df=df)
        from dashboard.pages.detalle import render

        render.__wrapped__(ctx)

        mock_st.warning.assert_called()


def _get_default_cols():
    from dashboard.pages.detalle import _DEFAULT_COLS

    return _DEFAULT_COLS
