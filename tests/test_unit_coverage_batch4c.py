"""Unit tests for scraper/pipeline.py and dashboard pages (competidores, partners, organos, tecnologias)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(df=None, df_full=None):
    """Build a minimal PageContext with a fake DataFrame."""
    if df is None:
        df = pd.DataFrame(
            {
                "id_externo": ["L1", "L2", "L3"],
                "titulo": ["SAP migration", "ERP upgrade", "Cloud project"],
                "descripcion": ["desc1", "desc2", "desc3"],
                "organo_contratacion": ["ORG_A", "ORG_B", "ORG_A"],
                "importe": [100_000.0, 200_000.0, 150_000.0],
                "estado_desc": ["Adjudicada", "En plazo", "Adjudicada"],
                "ccaa": ["Madrid", "Cataluña", "Madrid"],
                "tipo_proyecto": ["Servicios", "Suministros", "Servicios"],
                "cpv_desc": ["CPV1", "CPV2", "CPV1"],
                "fecha_publicacion": pd.to_datetime(["2024-01-15", "2024-02-20", "2024-03-10"]),
                "url": ["http://a", "http://b", "http://c"],
                "tecnologia": ["SAP", "ERP,BW", None],
                "modulos_str": ["FI", "MM", None],
            }
        )
    if df_full is None:
        df_full = df.copy()

    from dashboard.filters.state import FiltersState

    ctx = MagicMock()
    ctx.df = df
    ctx.df_full = df_full
    ctx.filters = FiltersState()
    ctx.plotly_template = "plotly_white"
    ctx.color_sequence = ["#86BC25", "#0076A8", "#E87722", "#6B3FA0"]
    return ctx


def _adj_df():
    """Minimal adjudicaciones DataFrame."""
    return pd.DataFrame(
        {
            "id": [1, 2, 3, 4],
            "licitacion_id": ["L1", "L1", "L2", "L3"],
            "empresa_key": ["EK1", "EK2", "EK1", "EK3"],
            "nombre_canonico": ["INDRA", "TELEFONICA", "INDRA", "ACCENTURE"],
            "nombre": ["Indra SA", "Telefónica SA", "Indra SA", "Accenture SL"],
            "nif_norm": ["A123", "B456", "A123", "C789"],
            "importe_adjudicado": [50_000.0, 30_000.0, 80_000.0, 60_000.0],
            "baja_pct": [10.0, 15.0, 5.0, 20.0],
            "n_ofertas_recibidas": [3, 1, 5, 2],
            "organo_contratacion": ["ORG_A", "ORG_A", "ORG_B", "ORG_A"],
            "fecha_adjudicacion": pd.to_datetime(
                ["2024-01-20", "2024-01-20", "2024-02-25", "2024-03-15"]
            ),
            "ccaa": ["Madrid", "Madrid", "Cataluña", "Madrid"],
            "es_ute": [0, 0, 1, 0],
            "es_pyme": [0, 1, 0, 1],
            "titulo": ["SAP migration", "SAP migration", "ERP upgrade", "Cloud project"],
            "url_lic": ["http://a", "http://a", "http://b", "http://c"],
        }
    )


# ===================================================================
# scraper/pipeline.py
# ===================================================================


class TestSignalPostIngestion:
    @patch("scraper.pipeline.log")
    def test_success(self, mock_log):
        with patch.dict(
            "sys.modules",
            {
                "shared.cache_signal": MagicMock(),
                "db.events": MagicMock(),
            },
        ):
            from scraper.pipeline import _signal_post_ingestion

            _signal_post_ingestion("test_source")

    @patch("scraper.pipeline.log")
    def test_cache_signal_fails(self, mock_log):
        # Remove cached module to force re-import failure
        mod = MagicMock()
        mod.signal_cache_invalidation.side_effect = RuntimeError("boom")
        with patch.dict("sys.modules", {"shared.cache_signal": mod, "db.events": MagicMock()}):
            from scraper.pipeline import _signal_post_ingestion

            _signal_post_ingestion("test")
            # Should not raise

    @patch("scraper.pipeline.log")
    def test_faiss_event_fails(self, mock_log):
        cache_mod = MagicMock()
        events_mod = MagicMock()
        events_mod.append_event.side_effect = RuntimeError("boom")
        with patch.dict("sys.modules", {"shared.cache_signal": cache_mod, "db.events": events_mod}):
            from scraper.pipeline import _signal_post_ingestion

            _signal_post_ingestion("test")


class TestProcessMonth:
    @patch("scraper.pipeline.close_pool")
    @patch("scraper.pipeline._signal_post_ingestion")
    @patch("scraper.pipeline.log_extraccion")
    @patch("scraper.pipeline.replace_adjudicaciones", return_value=2)
    @patch("scraper.pipeline.upsert_licitaciones", return_value=(3, 1))
    @patch("scraper.pipeline.iter_xml_files")
    @patch("scraper.pipeline.download_month", return_value="/var/tmp/test.zip")  # noqa: S108
    def test_ok(self, dl, iter_xml, upsert, repl_adj, log_ext, signal, close):
        from db.upsert import Licitacion
        from scraper.pipeline import process_month

        lic = Licitacion(id_externo="X1", titulo="Test")
        iter_xml.return_value = [("file.xml", b"<xml/>")]

        with patch("scraper.pipeline.parse_atom_bytes", return_value=[(lic, [{"adj": 1}])]):
            with patch("scraper.pipeline.log"):
                result = process_month(2024, 1)

        assert result["status"] == "ok"
        assert result["tech_matches"] == 1
        close.assert_called_once()

    @patch("scraper.pipeline.close_pool")
    @patch("scraper.pipeline.record_failure")
    @patch("scraper.pipeline.notify")
    @patch("scraper.pipeline.download_month")
    def test_circuit_open(self, dl, notify, rec, close):
        from scraper.bulk_downloader import CircuitOpenError
        from scraper.pipeline import process_month

        dl.side_effect = CircuitOpenError("open")
        with patch("scraper.pipeline.log"):
            result = process_month(2024, 1, run_id="r1")
        assert result["status"] == "circuit_open"
        close.assert_called_once()

    @patch("scraper.pipeline.close_pool")
    @patch("scraper.pipeline.record_failure")
    @patch("scraper.pipeline.download_month")
    def test_download_error(self, dl, rec, close):
        dl.side_effect = ConnectionError("fail")
        with patch("scraper.pipeline.log"):
            from scraper.pipeline import process_month

            result = process_month(2024, 1)
        assert result["status"] == "error_descarga"

    @patch("scraper.pipeline.close_pool")
    @patch("scraper.pipeline.download_month", return_value=None)
    def test_no_publicado(self, dl, close):
        with patch("scraper.pipeline.log"):
            from scraper.pipeline import process_month

            result = process_month(2024, 1)
        assert result["status"] == "no_publicado"

    @patch("scraper.pipeline.close_pool")
    @patch("scraper.pipeline.record_failure")
    @patch("scraper.pipeline.upsert_licitaciones")
    @patch("scraper.pipeline.iter_xml_files", return_value=[])
    @patch("scraper.pipeline.download_month", return_value="/var/tmp/t.zip")  # noqa: S108
    def test_persist_error(self, dl, iter_xml, upsert, rec, close):
        upsert.side_effect = RuntimeError("db error")
        with patch("scraper.pipeline.log"):
            from scraper.pipeline import process_month

            result = process_month(2024, 1)
        assert result["status"] == "error_persistencia"


class TestSummarize:
    def test_summarize_ok(self):
        from scraper.pipeline import _summarize

        metrics = MagicMock()
        metrics.months_attempted = 0
        metrics.months_ok = 0
        metrics.months_failed = 0
        metrics.licitaciones_nuevas = 0
        metrics.licitaciones_actualizadas = 0
        metrics.adjudicaciones = 0
        metrics.errores_parseo = 0
        metrics.errores_descarga = 0
        metrics.notas = ""

        results = [
            {
                "status": "ok",
                "nuevas": 5,
                "actualizadas": 2,
                "adjudicaciones": 3,
                "entries_error": 1,
                "adj_errors": 0,
            },
            {"status": "no_publicado"},
            {"status": "error_descarga"},
        ]
        _summarize(results, metrics)
        assert metrics.months_attempted == 3
        assert metrics.months_ok == 2
        assert metrics.months_failed == 1
        assert metrics.errores_descarga == 1

    def test_summarize_adj_errors(self):
        from scraper.pipeline import _summarize

        metrics = MagicMock()
        metrics.months_attempted = 0
        metrics.months_ok = 0
        metrics.months_failed = 0
        metrics.licitaciones_nuevas = 0
        metrics.licitaciones_actualizadas = 0
        metrics.adjudicaciones = 0
        metrics.errores_parseo = 0
        metrics.errores_descarga = 0
        metrics.notas = ""

        results = [
            {
                "status": "ok",
                "nuevas": 1,
                "actualizadas": 0,
                "adjudicaciones": 1,
                "entries_error": 0,
                "adj_errors": 2,
            },
        ]
        _summarize(results, metrics)
        assert metrics.notas == "adj_persist_errors:2"


class TestBackfill:
    def test_invalid_month(self):
        from scraper.pipeline import backfill

        with pytest.raises(ValueError, match="start_month"):
            backfill(2024, 13)

    def test_invalid_year(self):
        from scraper.pipeline import backfill

        with pytest.raises(ValueError, match="start_year"):
            backfill(1999, 1)


class TestProcessDaily:
    @patch("scraper.pipeline._signal_post_ingestion")
    @patch("scraper.pipeline.log_extraccion")
    @patch("scraper.pipeline.set_cursor")
    @patch("scraper.pipeline.replace_adjudicaciones", return_value=1)
    @patch("scraper.pipeline.get_cursor", return_value=None)
    @patch("scraper.pipeline.init_db")
    def test_no_entries(self, init, get_cur, repl, set_cur, log_ext, signal):
        mock_meta = {
            "pages_fetched": 1,
            "entries_seen": 0,
            "stopped_reason": "no_new",
            "etag": "e1",
            "last_modified": "lm1",
            "newest_updated": None,
        }
        with patch("scraper.atom_live.iter_live_entries", return_value=([], mock_meta)):
            with patch("scraper.pipeline.log"):
                from scraper.pipeline import process_daily

                result = process_daily()
        assert result["status"] == "ok"
        assert result["tech_matches"] == 0

    @patch("scraper.pipeline._signal_post_ingestion")
    @patch("scraper.pipeline.log_extraccion")
    @patch("scraper.pipeline.set_cursor")
    @patch("scraper.pipeline.replace_adjudicaciones", return_value=1)
    @patch("scraper.pipeline.get_cursor", return_value={"last_seen_updated": "2024-01-01"})
    @patch("scraper.pipeline.init_db")
    def test_with_entries(self, init, get_cur, repl, set_cur, log_ext, signal):
        from db.upsert import Licitacion, UpsertResult

        lic = Licitacion(id_externo="D1", titulo="Daily test")
        entry_elem = MagicMock()
        entries = [(entry_elem, "2024-01-02T00:00:00")]
        meta = {
            "pages_fetched": 1,
            "entries_seen": 1,
            "etag": None,
            "last_modified": None,
            "newest_updated": "2024-01-02T00:00:00",
        }

        upsert_result = UpsertResult(inserted=["D1"], modified=[], unchanged=[])

        with patch("scraper.atom_live.iter_live_entries", return_value=(entries, meta)):
            with patch("scraper.pipeline.parse_entry", return_value=lic):
                with patch("scraper.pipeline.parse_adjudicaciones", return_value=[]):
                    with patch(
                        "scraper.pipeline.upsert_licitaciones_with_history",
                        return_value=upsert_result,
                    ):
                        with patch("scraper.pipeline.log"):
                            from scraper.pipeline import process_daily

                            result = process_daily()

        assert result["status"] == "ok"
        assert result["tech_matches"] == 1

    @patch("scraper.pipeline.record_failure")
    @patch("scraper.pipeline.notify")
    @patch("scraper.pipeline.get_cursor", return_value=None)
    @patch("scraper.pipeline.init_db")
    def test_fetch_error(self, init, get_cur, notify, rec):
        with patch("scraper.atom_live.iter_live_entries", side_effect=ConnectionError("fail")):
            with patch("scraper.pipeline.log"):
                from scraper.pipeline import process_daily

                result = process_daily(run_id="r1")
        assert result["status"] == "error_fetch"

    @patch("scraper.pipeline._signal_post_ingestion")
    @patch("scraper.pipeline.log_extraccion")
    @patch("scraper.pipeline.set_cursor")
    @patch("scraper.pipeline.record_failure")
    @patch("scraper.pipeline.replace_adjudicaciones", return_value=0)
    @patch("scraper.pipeline.get_cursor", return_value={"last_seen_updated": "2024-01-01"})
    @patch("scraper.pipeline.init_db")
    def test_persist_error(self, init, get_cur, repl, rec, set_cur, log_ext, signal):
        entry_elem = MagicMock()
        entries = [(entry_elem, "2024-01-02")]
        meta = {
            "pages_fetched": 1,
            "entries_seen": 1,
            "etag": None,
            "last_modified": None,
            "newest_updated": None,
        }

        with patch("scraper.atom_live.iter_live_entries", return_value=(entries, meta)):
            with patch(
                "scraper.pipeline.parse_entry",
                return_value=MagicMock(id_externo="X", fecha_actualizacion_fuente=None),
            ):
                with patch("scraper.pipeline.parse_adjudicaciones", return_value=[]):
                    with patch(
                        "scraper.pipeline.upsert_licitaciones_with_history",
                        side_effect=RuntimeError("db"),
                    ):
                        with patch("scraper.pipeline.log"):
                            from scraper.pipeline import process_daily

                            result = process_daily(run_id="r1")
        assert result["status"] == "error_persistencia"


class TestUpdateDaily:
    @patch("scraper.pipeline.close_pool")
    @patch("scraper.pipeline.process_daily")
    @patch("scraper.pipeline.record_run")
    @patch("scraper.pipeline.bind_run_context", return_value="run1")
    @patch("scraper.pipeline.init_db")
    def test_ok(self, init, bind, record_run_cm, proc_daily, close):
        proc_daily.return_value = {
            "status": "ok",
            "inserted": ["A"],
            "modified": [],
            "source": "test",
        }
        mock_metrics = MagicMock()
        record_run_cm.return_value.__enter__ = MagicMock(return_value=mock_metrics)
        record_run_cm.return_value.__exit__ = MagicMock(return_value=False)

        with patch("scraper.pipeline.log"):
            from scraper.pipeline import update_daily

            result = update_daily()

        assert result["status"] == "ok"
        close.assert_called_once()

    @patch("scraper.pipeline.close_pool")
    @patch("scraper.pipeline.process_daily")
    @patch("scraper.pipeline.record_run")
    @patch("scraper.pipeline.bind_run_context", return_value="run1")
    @patch("scraper.pipeline.init_db")
    def test_error(self, init, bind, record_run_cm, proc_daily, close):
        proc_daily.return_value = {"status": "error_fetch", "source": "test"}
        mock_metrics = MagicMock()
        record_run_cm.return_value.__enter__ = MagicMock(return_value=mock_metrics)
        record_run_cm.return_value.__exit__ = MagicMock(return_value=False)

        with patch("scraper.pipeline.log"):
            from scraper.pipeline import update_daily

            result = update_daily()

        assert result["status"] == "error_fetch"


class TestApplyTechPrediction:
    def test_no_classifier(self):
        from scraper.pipeline import _apply_tech_prediction, _load_classifiers

        _load_classifiers.cache_clear()
        lic = MagicMock()
        with patch("scraper.pipeline._get_tech_clf", return_value=None):
            result = _apply_tech_prediction(lic)
        assert result is None

    def test_with_classifier(self):
        from scraper.pipeline import _apply_tech_prediction

        lic = MagicMock()
        lic.titulo = "SAP test"
        lic.descripcion = "description"
        lic.cpv = "72000000"
        lic.importe = 100000.0

        tech_clf = MagicMock()
        tech_clf.predict_one.return_value = {
            "predicted": ["SAP", "ERP"],
            "max_proba": 0.95,
            "principal": "SAP",
            "scores": {},
            "thresholds": {},
        }
        with patch("scraper.pipeline._get_tech_clf", return_value=tech_clf):
            result = _apply_tech_prediction(lic)
        assert result is not None
        assert lic.ml_tecnologias == "SAP,ERP"
        assert lic.ml_proba_max == 0.95

    def test_predict_fails(self):
        from scraper.pipeline import _apply_tech_prediction

        lic = MagicMock()
        lic.titulo = "test"
        lic.descripcion = ""
        lic.cpv = "72"
        lic.importe = 1.0
        lic.id_externo = "X1"

        tech_clf = MagicMock()
        tech_clf.predict_one.side_effect = RuntimeError("fail")
        with patch("scraper.pipeline._get_tech_clf", return_value=tech_clf):
            with patch("scraper.pipeline.log"):
                result = _apply_tech_prediction(lic)
        assert result is None


class TestMlClassifyEntry:
    def test_no_cpv(self):
        from scraper.pipeline import _ml_classify_entry

        entry = MagicMock()
        entry.xpath.return_value = []
        with patch("scraper.pipeline.log"):
            result = _ml_classify_entry(entry)
        assert result is None

    def test_non_ti_cpv(self):
        from scraper.pipeline import _ml_classify_entry

        entry = MagicMock()
        entry.xpath.return_value = ["90000000"]
        with patch("scraper.pipeline.log"):
            result = _ml_classify_entry(entry)
        assert result is None

    def test_no_clf(self):
        from scraper.pipeline import _load_classifiers, _ml_classify_entry

        _load_classifiers.cache_clear()
        entry = MagicMock()
        entry.xpath.return_value = ["72000000"]
        with patch("scraper.pipeline._get_ml_clf", return_value=None):
            with patch("scraper.pipeline.log"):
                result = _ml_classify_entry(entry)
        assert result is None

    def test_parse_returns_none(self):
        from scraper.pipeline import _ml_classify_entry

        entry = MagicMock()
        entry.xpath.return_value = ["48000000"]
        clf = MagicMock()
        with patch("scraper.pipeline._get_ml_clf", return_value=clf):
            with patch("scraper.pipeline.parse_entry_unfiltered", return_value=None):
                with patch("scraper.pipeline.log"):
                    result = _ml_classify_entry(entry)
        assert result is None


class TestUpdateRecent:
    @patch("scraper.pipeline.process_month")
    @patch("scraper.pipeline._summarize")
    @patch("scraper.pipeline.record_run")
    @patch("scraper.pipeline.bind_run_context", return_value="r1")
    @patch("scraper.pipeline.init_db")
    def test_update_recent(self, init, bind, record_run_cm, summarize, proc):
        mock_metrics = MagicMock()
        record_run_cm.return_value.__enter__ = MagicMock(return_value=mock_metrics)
        record_run_cm.return_value.__exit__ = MagicMock(return_value=False)
        proc.return_value = {"status": "ok", "year": 2024, "month": 1}

        with patch("scraper.pipeline.log"):
            from scraper.pipeline import update_recent

            results = update_recent(months_back=2)
        assert len(results) == 2


# ===================================================================
# Dashboard pages — mock streamlit
# ===================================================================


# We need to mock st globally for dashboard page imports
def _make_st_mock():
    """Create a fresh streamlit mock with dynamic columns support."""
    m = MagicMock()
    m.query_params = {}

    def _columns(n=2, **kwargs):
        if isinstance(n, int):
            return [MagicMock() for _ in range(n)]
        if isinstance(n, (list, tuple)):
            return [MagicMock() for _ in n]
        return [MagicMock(), MagicMock()]

    m.columns.side_effect = _columns

    def _tabs(labels):
        cms = []
        for _ in labels:
            cm = MagicMock()
            cm.__enter__ = MagicMock(return_value=cm)
            cm.__exit__ = MagicMock(return_value=False)
            cms.append(cm)
        return cms

    m.tabs.side_effect = _tabs
    m.multiselect.return_value = []
    m.text_input.return_value = ""
    m.selectbox.return_value = None
    m.slider.return_value = 2
    m.number_input.return_value = 20
    m.radio.return_value = "Nº licitaciones"
    exp = MagicMock()
    exp.__enter__ = MagicMock(return_value=exp)
    exp.__exit__ = MagicMock(return_value=False)
    m.expander.return_value = exp
    cont = MagicMock()
    cont.__enter__ = MagicMock(return_value=cont)
    cont.__exit__ = MagicMock(return_value=False)
    m.container.return_value = cont
    m.column_config = MagicMock()
    return m


_st_mock = _make_st_mock()


_DASHBOARD_ST_PATCHES = [
    "dashboard.components.states.st",
    "dashboard.components.cards.st",
    "dashboard.components.tables.st",
]


def _patch_all_st(st_mock, extra_patches=None):
    """Return a list of patch context managers for all dashboard st modules."""
    patches = [patch(p, st_mock) for p in _DASHBOARD_ST_PATCHES]
    for ep in extra_patches or []:
        patches.append(patch(ep, st_mock))
    return patches


def _apply_patches(patches):
    """Enter all patches and return list of mocks."""
    return [p.__enter__() for p in patches]


def _unapply_patches(patches):
    for p in patches:
        p.__exit__(None, None, None)


class TestCompetidoresRender:
    def test_empty_adj(self):
        patches = _patch_all_st(_st_mock, ["dashboard.pages.competidores._main.st"])
        _apply_patches(patches)
        try:
            with patch(
                "dashboard.pages.competidores._main.load_adjudicaciones",
                return_value=pd.DataFrame(),
            ):
                from dashboard.pages.competidores._main import render

                fn = getattr(render, "__wrapped__", render)
                ctx = _make_ctx()
                fn(ctx)
        finally:
            _unapply_patches(patches)

    def test_with_adj(self):
        patches = _patch_all_st(_st_mock, ["dashboard.pages.competidores._main.st"])
        _apply_patches(patches)
        try:
            with patch(
                "dashboard.pages.competidores._main.load_adjudicaciones", return_value=_adj_df()
            ):
                from dashboard.pages.competidores._main import render

                fn = getattr(render, "__wrapped__", render)
                ctx = _make_ctx()
                fn(ctx)
        finally:
            _unapply_patches(patches)

    def test_adj_filtered_empty(self):
        patches = _patch_all_st(_st_mock, ["dashboard.pages.competidores._main.st"])
        _apply_patches(patches)
        try:
            adj = _adj_df()
            adj["licitacion_id"] = ["Z1", "Z2", "Z3", "Z4"]
            with patch("dashboard.pages.competidores._main.load_adjudicaciones", return_value=adj):
                from dashboard.pages.competidores._main import render

                fn = getattr(render, "__wrapped__", render)
                ctx = _make_ctx()
                fn(ctx)
        finally:
            _unapply_patches(patches)


class TestPartnersRender:
    def test_empty_adj(self):
        patches = _patch_all_st(_st_mock, ["dashboard.pages.partners.st"])
        _apply_patches(patches)
        try:
            with patch("dashboard.pages.partners.load_adjudicaciones", return_value=pd.DataFrame()):
                from dashboard.pages.partners import render

                fn = getattr(render, "__wrapped__", render)
                fn(_make_ctx())
        finally:
            _unapply_patches(patches)

    def test_with_adj(self):
        patches = _patch_all_st(_st_mock, ["dashboard.pages.partners.st"])
        _apply_patches(patches)
        try:
            with (
                patch("dashboard.pages.partners.load_adjudicaciones", return_value=_adj_df()),
                patch(
                    "dashboard.pages.partners.build_partnership_graph",
                    return_value={"nodes": [], "edges": []},
                ),
                patch("dashboard.pages.partners.segment_winners", return_value=pd.DataFrame()),
                patch("dashboard.pages.partners.suggest_partners", return_value=pd.DataFrame()),
            ):
                from dashboard.pages.partners import render

                fn = getattr(render, "__wrapped__", render)
                fn(_make_ctx())
        finally:
            _unapply_patches(patches)

    def test_filtered_empty(self):
        patches = _patch_all_st(_st_mock, ["dashboard.pages.partners.st"])
        _apply_patches(patches)
        try:
            adj = _adj_df()
            adj["licitacion_id"] = ["Z1", "Z2", "Z3", "Z4"]
            with patch("dashboard.pages.partners.load_adjudicaciones", return_value=adj):
                from dashboard.pages.partners import render

                fn = getattr(render, "__wrapped__", render)
                fn(_make_ctx())
        finally:
            _unapply_patches(patches)


class TestRenderGraphTab:
    def test_no_nodes(self):
        patches = _patch_all_st(_st_mock, ["dashboard.pages.partners.st"])
        _apply_patches(patches)
        try:
            with patch(
                "dashboard.pages.partners.build_partnership_graph",
                return_value={"nodes": [], "edges": []},
            ):
                from dashboard.pages.partners import _render_graph_tab

                _render_graph_tab(_make_ctx(), _adj_df())
        finally:
            _unapply_patches(patches)


class TestRenderSegmentTab:
    def test_empty_ranking(self):
        patches = _patch_all_st(_st_mock, ["dashboard.pages.partners.st"])
        _apply_patches(patches)
        try:
            with patch("dashboard.pages.partners.segment_winners", return_value=pd.DataFrame()):
                from dashboard.pages.partners import _render_segment_tab

                _render_segment_tab(_make_ctx(), _adj_df())
        finally:
            _unapply_patches(patches)

    def test_with_keyword(self):
        _st_mock.text_input.return_value = "SAP"
        patches = _patch_all_st(_st_mock, ["dashboard.pages.partners.st"])
        _apply_patches(patches)
        try:
            ranking = pd.DataFrame(
                {
                    "empresa": ["INDRA"],
                    "empresa_key": ["EK1"],
                    "n_contratos": [5],
                    "importe_total": [100000],
                    "cuota_pct": [50.0],
                    "ticket_medio": [20000],
                    "n_organos": [3],
                }
            )
            with patch("dashboard.pages.partners.suggest_partners", return_value=ranking):
                from dashboard.pages.partners import _render_segment_tab

                _render_segment_tab(_make_ctx(), _adj_df())
        finally:
            _st_mock.text_input.return_value = ""
            _unapply_patches(patches)


class TestRenderPartnersTab:
    def test_no_keywords(self):
        _st_mock.text_input.return_value = ""
        patches = _patch_all_st(_st_mock, ["dashboard.pages.partners.st"])
        _apply_patches(patches)
        try:
            from dashboard.pages.partners import _render_partners_tab

            _render_partners_tab(_make_ctx(), _adj_df())
        finally:
            _unapply_patches(patches)

    def test_with_keywords_empty_results(self):
        _st_mock.text_input.return_value = "SAP, ERP"
        _st_mock.selectbox.return_value = "Todas"
        _st_mock.number_input.return_value = 100000
        patches = _patch_all_st(_st_mock, ["dashboard.pages.partners.st"])
        _apply_patches(patches)
        try:
            with patch("dashboard.pages.partners.suggest_partners", return_value=pd.DataFrame()):
                from dashboard.pages.partners import _render_partners_tab

                _render_partners_tab(_make_ctx(), _adj_df())
        finally:
            _st_mock.text_input.return_value = ""
            _st_mock.selectbox.return_value = None
            _unapply_patches(patches)


class TestRenderCompanyCard:
    def test_render_card(self):
        patches = _patch_all_st(_st_mock, ["dashboard.pages.partners.st"])
        _apply_patches(patches)
        try:
            from dashboard.pages.partners import _render_company_card

            profile = {
                "nombre": "INDRA",
                "n_contratos": 10,
                "importe_total": 500000,
                "ticket_medio": 50000,
                "pct_ute": 30.0,
                "es_pyme": False,
                "ccaas": ["Madrid", "Cataluña"],
                "top_organos": {"ORG_A": 5, "ORG_B": 3},
                "ute_partners": {"TELEFONICA": 2},
                "top_cpvs": {"72000000": 8},
            }
            _render_company_card(profile, _make_ctx())
        finally:
            _unapply_patches(patches)


class TestOrganosRender:
    def test_render_no_selection(self):
        _st_mock.selectbox.return_value = None
        patches = _patch_all_st(_st_mock, ["dashboard.pages.organos.st"])
        _apply_patches(patches)
        try:
            with patch("dashboard.pages.organos.load_adjudicaciones", return_value=_adj_df()):
                from dashboard.pages.organos import render

                fn = getattr(render, "__wrapped__", render)
                fn(_make_ctx())
        finally:
            _unapply_patches(patches)

    def test_render_with_selection(self):
        _st_mock.selectbox.return_value = "ORG_A"
        patches = _patch_all_st(_st_mock, ["dashboard.pages.organos.st"])
        _apply_patches(patches)
        try:
            with (
                patch("dashboard.pages.organos.load_adjudicaciones", return_value=_adj_df()),
                patch(
                    "dashboard.pages.organos.kpis_organo",
                    return_value={
                        "n_lics": 10,
                        "importe_total": 500000,
                        "importe_medio": 50000,
                        "pct_adj": 60.0,
                        "lead_time_dias": 30,
                        "top_adjudicatario": "INDRA",
                        "top_adj_importe": 200000,
                    },
                ),
                patch(
                    "dashboard.pages.organos.score_oportunidad",
                    return_value=pd.DataFrame(
                        {
                            "id_externo": ["L1", "L3"],
                            "score": [80, 60],
                            "banda": ["A", "B"],
                        }
                    ),
                ),
            ):
                from dashboard.pages.organos import render

                fn = getattr(render, "__wrapped__", render)
                fn(_make_ctx())
        finally:
            _st_mock.selectbox.return_value = None
            _unapply_patches(patches)

    def test_render_score_fails(self):
        _st_mock.selectbox.return_value = "ORG_A"
        patches = _patch_all_st(_st_mock, ["dashboard.pages.organos.st"])
        _apply_patches(patches)
        try:
            with (
                patch("dashboard.pages.organos.load_adjudicaciones", return_value=_adj_df()),
                patch(
                    "dashboard.pages.organos.kpis_organo",
                    return_value={
                        "n_lics": 2,
                        "importe_total": 100000,
                        "importe_medio": 50000,
                        "pct_adj": 50.0,
                        "lead_time_dias": None,
                        "top_adjudicatario": None,
                        "top_adj_importe": 0,
                    },
                ),
                patch(
                    "dashboard.pages.organos.score_oportunidad",
                    side_effect=RuntimeError("score fail"),
                ),
            ):
                from dashboard.pages.organos import render

                fn = getattr(render, "__wrapped__", render)
                fn(_make_ctx())
        finally:
            _st_mock.selectbox.return_value = None
            _unapply_patches(patches)


class TestTecnologiasExplode:
    def test_explode(self):
        from dashboard.pages.tecnologias import _explode_tecnologias

        df = pd.DataFrame(
            {
                "id_externo": ["L1", "L2"],
                "tecnologia": ["SAP,ERP", None],
            }
        )
        result = _explode_tecnologias(df)
        assert len(result) == 3  # SAP, ERP, SIN_CLASIFICAR
        assert "tech_label" in result.columns

    def test_explode_single(self):
        from dashboard.pages.tecnologias import _explode_tecnologias

        df = pd.DataFrame(
            {
                "id_externo": ["L1"],
                "tecnologia": ["SAP"],
            }
        )
        result = _explode_tecnologias(df)
        assert len(result) == 1


class TestTecnologiasRender:
    def test_render_default(self):
        _st_mock.selectbox.return_value = None
        _st_mock.radio.return_value = "Nº licitaciones"
        patches = _patch_all_st(_st_mock, ["dashboard.pages.tecnologias.st"])
        _apply_patches(patches)
        try:
            from dashboard.pages.tecnologias import render

            fn = getattr(render, "__wrapped__", render)
            fn(_make_ctx())
        finally:
            _unapply_patches(patches)

    def test_render_with_tech_selected(self):
        _st_mock.selectbox.return_value = "SAP"
        _st_mock.radio.return_value = "Importe acumulado"
        patches = _patch_all_st(_st_mock, ["dashboard.pages.tecnologias.st"])
        _apply_patches(patches)
        try:
            with (
                patch(
                    "dashboard.pages.tecnologias.score_oportunidad",
                    return_value=pd.DataFrame(
                        {
                            "id_externo": ["L1"],
                            "score": [80],
                            "banda": ["A"],
                        }
                    ),
                ),
                patch("dashboard.pages.tecnologias.tecnologia_label", side_effect=lambda t: t),
            ):
                from dashboard.pages.tecnologias import render

                fn = getattr(render, "__wrapped__", render)
                fn(_make_ctx())
        finally:
            _st_mock.selectbox.return_value = None
            _st_mock.radio.return_value = "Nº licitaciones"
            _unapply_patches(patches)

    def test_render_score_fails(self):
        _st_mock.selectbox.return_value = "SAP"
        patches = _patch_all_st(_st_mock, ["dashboard.pages.tecnologias.st"])
        _apply_patches(patches)
        try:
            with (
                patch(
                    "dashboard.pages.tecnologias.score_oportunidad",
                    side_effect=RuntimeError("fail"),
                ),
                patch("dashboard.pages.tecnologias.tecnologia_label", side_effect=lambda t: t),
            ):
                from dashboard.pages.tecnologias import render

                fn = getattr(render, "__wrapped__", render)
                fn(_make_ctx())
        finally:
            _st_mock.selectbox.return_value = None
            _unapply_patches(patches)
