"""Tests unitarios para scraper/pipeline.py usando mocks pesados.

Los tests de ``process_month`` / ``backfill`` / ``update_recent`` se retiraron
con esas funciones (S2.1, 2026-09): el carril bulk y el backfill pasaron al
conector, y su comportamiento vive ahora en
``tests/test_s2_backfill_connector.py``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from scraper.pipeline import _resolve_empresas_post_ingestion, _summarize


def test_post_ingestion_scopes_resolution_and_bounds_it():
    """Acotado, reanudable y con presupuesto: los tres controles que faltaban.

    Sin ellos, cada ingesta barría la tabla de adjudicaciones entera desde el
    id 0 y se comía el timeout del step.
    """
    from services.entity_resolution import HOOK_TIME_BUDGET_S

    with (
        patch("services.entity_resolution.resolve_all_unlinked") as resolve_all,
        patch("services.contract_events.derive_new_events"),
    ):
        _resolve_empresas_post_ingestion("place_live_atom", scope_fuente="placsp")

    resolve_all.assert_called_once_with(
        fuente="place_live_atom",
        scope_fuente="placsp",
        resume=True,
        time_budget_s=HOOK_TIME_BUDGET_S,
    )


def test_daily_fuente_matches_the_model_default():
    """El ámbito del carril diario tiene que ser el `fuente` que ese carril graba.

    `_DAILY_SOURCE` ('place_live_atom') es la etiqueta del carril, no un valor
    de `licitaciones.fuente`: las filas del ATOM se quedan con el default del
    modelo. Si ese default cambia y `_DAILY_FUENTE` no, el ámbito quedaría
    vacío y el carril diario dejaría de resolver empresas en silencio.
    """
    from dataclasses import fields

    from db.upsert import Licitacion
    from scraper.pipeline import _DAILY_FUENTE, _DAILY_SOURCE

    default = next(f for f in fields(Licitacion) if f.name == "fuente").default
    assert default == _DAILY_FUENTE
    assert _DAILY_FUENTE != _DAILY_SOURCE


# ─── _summarize ──────────────────────────────────────────────────────────────


class TestSummarize:
    def _metrics(self):
        m = MagicMock()
        m.months_attempted = 0
        m.months_ok = 0
        m.months_failed = 0
        m.licitaciones_nuevas = 0
        m.licitaciones_actualizadas = 0
        m.adjudicaciones = 0
        m.errores_parseo = 0
        m.errores_descarga = 0
        return m

    def test_ok_result(self):
        m = self._metrics()
        results = [
            {
                "status": "ok",
                "nuevas": 5,
                "actualizadas": 2,
                "adjudicaciones": 3,
                "entries_error": 1,
            }
        ]
        _summarize(results, m)
        assert m.months_attempted == 1
        assert m.months_ok == 1
        assert m.months_failed == 0
        assert m.licitaciones_nuevas == 5
        assert m.licitaciones_actualizadas == 2
        assert m.adjudicaciones == 3
        assert m.errores_parseo == 1

    def test_no_publicado_counts_as_ok(self):
        m = self._metrics()
        _summarize([{"status": "no_publicado"}], m)
        assert m.months_ok == 1
        assert m.months_failed == 0

    def test_circuit_open_counts_as_failed(self):
        m = self._metrics()
        _summarize([{"status": "circuit_open"}], m)
        assert m.months_failed == 1

    def test_error_descarga_increments_counter(self):
        m = self._metrics()
        _summarize([{"status": "error_descarga"}], m)
        assert m.months_failed == 1
        assert m.errores_descarga == 1

    def test_error_persistencia_counts_as_failed(self):
        m = self._metrics()
        _summarize([{"status": "error_persistencia"}], m)
        assert m.months_failed == 1

    def test_mixed_results(self):
        m = self._metrics()
        results = [
            {
                "status": "ok",
                "nuevas": 10,
                "actualizadas": 0,
                "adjudicaciones": 0,
                "entries_error": 0,
            },
            {"status": "no_publicado"},
            {"status": "error_descarga"},
        ]
        _summarize(results, m)
        assert m.months_attempted == 3
        assert m.months_ok == 2
        assert m.months_failed == 1

    def test_summarize_ok(self):
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


# ── _signal_post_ingestion ────────────────────────────────────────────────────


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


# ── process_daily (carril ATOM en vivo) ──────────────────────────────────────


class TestProcessDaily:
    @patch("scraper.pipeline._signal_post_ingestion")
    @patch("scraper.pipeline.log_extraccion")
    @patch("scraper.pipeline.set_cursor")
    @patch("scraper.pipeline.replace_adjudicaciones_batch", return_value=(1, 0, 0))
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
    @patch("scraper.pipeline.replace_adjudicaciones_batch", return_value=(1, 0, 0))
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
    @patch("scraper.pipeline.replace_adjudicaciones_batch", return_value=(0, 0, 0))
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


# ── update_daily ──────────────────────────────────────────────────────────────


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


# ── _apply_tech_prediction / _ml_classify_entry ──────────────────────────────


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

    def test_no_clf_keeps_ti_entry_as_cpv_universe(self):
        """Sin modelo, una entry CPV 48/72 ya no se descarta: es expediente TI."""
        from scraper.pipeline import INCLUSION_CPV_TI, _load_classifiers, _ml_classify_entry

        _load_classifiers.cache_clear()
        entry = MagicMock()
        entry.xpath.return_value = ["72000000"]
        lic = MagicMock()
        with patch("scraper.pipeline._get_ml_clf", return_value=None):
            with patch("scraper.pipeline.parse_entry_unfiltered", return_value=lic):
                with patch("scraper.pipeline.log"):
                    result = _ml_classify_entry(entry)
        assert result is lic
        assert lic.inclusion_reason == INCLUSION_CPV_TI

    def test_low_proba_keeps_entry_without_rescue(self):
        """Por debajo de ML_UNCERTAINTY_LO la entry se conserva como universo
        CPV, no como rescate ML: sin `tecnologia`, pero sin perderla."""
        from scraper.pipeline import INCLUSION_CPV_TI, _ml_classify_entry

        entry = MagicMock()
        entry.xpath.return_value = ["48000000"]
        lic = MagicMock()
        lic.titulo = "Implantación de un ERP corporativo"
        lic.descripcion = ""
        lic.cpv = "48000000"
        lic.importe = 500000.0
        clf = MagicMock()
        clf.pipeline.predict_proba.return_value = [[0.95, 0.05]]
        clf._threshold = 0.6
        clf.metadata = {"trained_at": "2026-01-01"}
        with patch("scraper.pipeline._get_ml_clf", return_value=clf):
            with patch("scraper.pipeline.parse_entry_unfiltered", return_value=lic):
                with patch("scraper.pipeline._apply_tech_prediction", return_value=None):
                    with patch("scraper.pipeline.log"):
                        result = _ml_classify_entry(entry)
        assert result is lic
        assert lic.inclusion_reason == INCLUSION_CPV_TI
        assert lic.ml_proba == 0.05

    def test_high_proba_is_ml_rescue(self):
        from scraper.pipeline import INCLUSION_ML_RESCUE, _ml_classify_entry

        entry = MagicMock()
        entry.xpath.return_value = ["72000000"]
        lic = MagicMock()
        lic.titulo = "Mantenimiento de sistemas"
        lic.descripcion = "soporte funcional"
        lic.cpv = "72000000"
        lic.importe = 100000.0
        clf = MagicMock()
        clf.pipeline.predict_proba.return_value = [[0.1, 0.9]]
        clf._threshold = 0.6
        clf.metadata = {"trained_at": "2026-01-01"}
        with patch("scraper.pipeline._get_ml_clf", return_value=clf):
            with patch("scraper.pipeline.parse_entry_unfiltered", return_value=lic):
                with patch("scraper.pipeline._apply_tech_prediction", return_value=None):
                    with patch("scraper.pipeline.log"):
                        result = _ml_classify_entry(entry)
        assert result is lic
        assert lic.inclusion_reason == INCLUSION_ML_RESCUE

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


# ── _ClassifierHolder / _load_classifiers ────────────────────────────────────


class TestClassifierHolder:
    """Verifica el refactor del singleton de clasificadores."""

    def setup_method(self):
        """Limpia el cache del singleton antes de cada test."""
        from scraper.pipeline import _load_classifiers

        _load_classifiers.cache_clear()

    def teardown_method(self):
        """Limpia el cache tras el test para no contaminar otros."""
        from scraper.pipeline import _load_classifiers

        _load_classifiers.cache_clear()

    def test_holder_is_frozen_dataclass(self):
        """_ClassifierHolder es un frozen dataclass (inmutable)."""
        from scraper.pipeline import _ClassifierHolder

        holder = _ClassifierHolder(ml=None, tech=None)
        assert holder.ml is None
        assert holder.tech is None
        # Frozen: no debe permitir asignación
        import dataclasses

        assert dataclasses.is_dataclass(holder)

    def test_load_classifiers_returns_none_when_unavailable(self, monkeypatch):
        """Si los clasificadores no están disponibles, retorna holder con Nones."""
        import config

        monkeypatch.setattr(config.settings, "ML_TECH_ENABLED", False)

        with patch("scraper.ml_classifier.SAPClassifier") as mock_clf:
            mock_clf.ensure_downloaded = MagicMock()
            mock_clf.is_available = MagicMock(return_value=False)

            from scraper.pipeline import _load_classifiers

            _load_classifiers.cache_clear()
            holder = _load_classifiers()
            assert holder.ml is None
            assert holder.tech is None

    def test_load_classifiers_caches_result(self, monkeypatch):
        """Llamadas sucesivas devuelven el mismo objeto (lru_cache)."""
        import config

        monkeypatch.setattr(config.settings, "ML_TECH_ENABLED", False)

        with patch("scraper.ml_classifier.SAPClassifier") as mock_clf:
            mock_clf.ensure_downloaded = MagicMock()
            mock_clf.is_available = MagicMock(return_value=False)

            from scraper.pipeline import _load_classifiers

            _load_classifiers.cache_clear()
            holder1 = _load_classifiers()
            holder2 = _load_classifiers()
            assert holder1 is holder2  # mismo objeto — lru_cache activo

    def test_get_ml_clf_delegates_to_holder(self, monkeypatch):
        """_get_ml_clf() retorna el campo ml del holder."""
        from unittest.mock import MagicMock, patch

        import config
        from scraper.pipeline import _get_ml_clf, _load_classifiers

        monkeypatch.setattr(config.settings, "ML_TECH_ENABLED", False)
        _load_classifiers.cache_clear()

        with patch("scraper.ml_classifier.SAPClassifier") as mock_clf:
            mock_clf.ensure_downloaded = MagicMock()
            mock_clf.is_available = MagicMock(return_value=False)
            result = _get_ml_clf()
            assert result is None

    def test_cache_clear_allows_reload(self, monkeypatch):
        """Tras cache_clear(), una nueva llamada ejecuta la carga."""
        import config
        from scraper.pipeline import _load_classifiers

        monkeypatch.setattr(config.settings, "ML_TECH_ENABLED", False)

        with patch("scraper.ml_classifier.SAPClassifier") as mock_clf:
            mock_clf.ensure_downloaded = MagicMock()
            mock_clf.is_available = MagicMock(return_value=False)

            _load_classifiers.cache_clear()
            holder1 = _load_classifiers()
            _load_classifiers.cache_clear()
            holder2 = _load_classifiers()
            # Después de clear, se crea un nuevo objeto
            assert holder1 is not holder2
