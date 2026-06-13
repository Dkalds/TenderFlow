"""Unit tests for scraper/pipeline.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

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
    @patch("scraper.pipeline.replace_adjudicaciones_batch", return_value=(2, 0))
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
    @patch("scraper.pipeline.replace_adjudicaciones_batch", return_value=(1, 0))
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
    @patch("scraper.pipeline.replace_adjudicaciones_batch", return_value=(1, 0))
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
    @patch("scraper.pipeline.replace_adjudicaciones_batch", return_value=(0, 0))
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


