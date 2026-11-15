"""Tests unitarios para scraper/pipeline.py usando mocks pesados.

Los tests de ``process_month`` / ``backfill`` / ``update_recent`` se retiraron
con esas funciones (S2.1, 2026-09): el carril bulk y el backfill pasaron al
conector, y su comportamiento vive ahora en
``tests/test_s2_backfill_connector.py``. Los de ``process_daily`` y sus pasos
post-ingesta se retiraron con él (2026-11): la resolución acotada, los eventos
de contrato y la señal de caché del camino vivo los cubre
``tests/test_connectors.py``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from scraper.pipeline import _summarize

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

        with patch("services.ml.sap_classifier.SAPClassifier") as mock_clf:
            mock_clf.resolve_artifact = MagicMock(return_value=None)

            from scraper.pipeline import _load_classifiers

            _load_classifiers.cache_clear()
            holder = _load_classifiers()
            assert holder.ml is None
            assert holder.tech is None

    def test_load_classifiers_caches_result(self, monkeypatch):
        """Llamadas sucesivas devuelven el mismo objeto (lru_cache)."""
        import config

        monkeypatch.setattr(config.settings, "ML_TECH_ENABLED", False)

        with patch("services.ml.sap_classifier.SAPClassifier") as mock_clf:
            mock_clf.resolve_artifact = MagicMock(return_value=None)

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

        with patch("services.ml.sap_classifier.SAPClassifier") as mock_clf:
            mock_clf.resolve_artifact = MagicMock(return_value=None)
            result = _get_ml_clf()
            assert result is None

    def test_cache_clear_allows_reload(self, monkeypatch):
        """Tras cache_clear(), una nueva llamada ejecuta la carga."""
        import config
        from scraper.pipeline import _load_classifiers

        monkeypatch.setattr(config.settings, "ML_TECH_ENABLED", False)

        with patch("services.ml.sap_classifier.SAPClassifier") as mock_clf:
            mock_clf.resolve_artifact = MagicMock(return_value=None)

            _load_classifiers.cache_clear()
            holder1 = _load_classifiers()
            _load_classifiers.cache_clear()
            holder2 = _load_classifiers()
            # Después de clear, se crea un nuevo objeto
            assert holder1 is not holder2

    def test_la_ingesta_carga_el_artefacto_que_resuelve_el_registro(self, monkeypatch, tmp_path):
        """`resolve_artifact` + `load(ruta)`, no `ensure_downloaded` + `load()`.

        Con la versión activa nombrada por contenido, `load()` sin ruta no
        encuentra su `path` en el runner y sirve el `sap_classifier.pkl` de
        nombre fijo que `ensure_downloaded` acaba de bajar, sin cotejar nada.
        """
        import config
        from scraper.pipeline import _load_classifiers

        monkeypatch.setattr(config.settings, "ML_TECH_ENABLED", False)
        artefacto = tmp_path / "sap_classifier-0123456789ab.pkl"
        cargado = MagicMock(_threshold=0.5)

        with patch("services.ml.sap_classifier.SAPClassifier") as mock_clf:
            mock_clf.resolve_artifact = MagicMock(return_value=artefacto)
            mock_clf.load = MagicMock(return_value=cargado)
            _load_classifiers.cache_clear()
            holder = _load_classifiers()

        assert holder.ml is cargado
        mock_clf.load.assert_called_once_with(artefacto)
        mock_clf.ensure_downloaded.assert_not_called()
        _load_classifiers.cache_clear()

    def test_un_artefacto_que_no_cuadra_deja_la_ingesta_sin_modelo(self, monkeypatch):
        """La ingesta sigue (las TI sin keyword van a `cpv_ti_universe`), pero
        no sirve el modelo equivocado ni cae a otro."""
        import config
        from scraper.pipeline import _load_classifiers
        from services.ml.model_artifacts import ModelArtifactMismatch

        monkeypatch.setattr(config.settings, "ML_TECH_ENABLED", False)

        with patch("services.ml.sap_classifier.SAPClassifier") as mock_clf:
            mock_clf.resolve_artifact = MagicMock(side_effect=ModelArtifactMismatch("no cuadra"))
            _load_classifiers.cache_clear()
            holder = _load_classifiers()

        assert holder.ml is None
        mock_clf.load.assert_not_called()
        _load_classifiers.cache_clear()
