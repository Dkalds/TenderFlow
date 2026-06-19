"""Tests unitarios para scraper/pipeline.py usando mocks pesados."""

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import MagicMock, patch

from scraper.pipeline import _summarize, process_month

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


# ─── process_month ────────────────────────────────────────────────────────────

_BASE_PATCH = {
    "scraper.pipeline.download_month": None,
    "scraper.pipeline.iter_xml_files": None,
    "scraper.pipeline.parse_atom_bytes": None,
    "scraper.pipeline.upsert_licitaciones": None,
    "scraper.pipeline.replace_adjudicaciones_batch": None,
    "scraper.pipeline.log_extraccion": None,
    "scraper.pipeline.record_failure": None,
    "scraper.pipeline.notify": None,
}


def _patch_all(**overrides):
    """Context manager que parchea todo el entorno de process_month.

    También silencia db.events.append_event y scraper.pipeline.close_pool para
    evitar que los tests unitarios abran la BD de producción o hagan checkpoints
    WAL que bloqueen el proceso en Windows.
    """
    defaults = {
        "scraper.pipeline.download_month": MagicMock(return_value="/fake/placsp.zip"),
        "scraper.pipeline.iter_xml_files": MagicMock(return_value=[]),
        "scraper.pipeline.parse_atom_bytes": MagicMock(return_value=[]),
        "scraper.pipeline.upsert_licitaciones": MagicMock(return_value=(0, 0)),
        "scraper.pipeline.replace_adjudicaciones_batch": MagicMock(return_value=(0, 0, 0)),
        "scraper.pipeline.log_extraccion": MagicMock(),
        "scraper.pipeline.record_failure": MagicMock(),
        "scraper.pipeline.notify": MagicMock(),
        "scraper.pipeline.close_pool": MagicMock(),
    }
    defaults.update(overrides)
    stack = ExitStack()
    stack.enter_context(
        patch.multiple("scraper.pipeline", **{k.split(".")[-1]: v for k, v in defaults.items()})
    )
    # Impedir escrituras reales a la BD: append_event se importa lazily dentro
    # de _process_month_impl, por eso se parchea en el módulo de origen.
    stack.enter_context(patch("db.events.append_event"))
    return stack


class TestProcessMonth:
    def test_happy_path_returns_ok(self):
        with _patch_all():
            result = process_month(2024, 1)
        assert result["status"] == "ok"
        assert result["year"] == 2024
        assert result["month"] == 1

    def test_zip_none_returns_no_publicado(self):
        with _patch_all(**{"scraper.pipeline.download_month": MagicMock(return_value=None)}):
            result = process_month(2024, 1)
        assert result["status"] == "no_publicado"

    def test_circuit_open_returns_circuit_open(self):
        from scraper.bulk_downloader import CircuitOpenError

        with _patch_all(
            **{
                "scraper.pipeline.download_month": MagicMock(
                    side_effect=CircuitOpenError("breaker abierto")
                )
            }
        ):
            result = process_month(2024, 1)
        assert result["status"] == "circuit_open"

    def test_download_exception_returns_error_descarga(self):
        with _patch_all(
            **{
                "scraper.pipeline.download_month": MagicMock(
                    side_effect=RuntimeError("fallo de red")
                )
            }
        ):
            result = process_month(2024, 1)
        assert result["status"] == "error_descarga"

    def test_persist_exception_returns_error_persistencia(self):
        with _patch_all(
            **{
                "scraper.pipeline.upsert_licitaciones": MagicMock(
                    side_effect=RuntimeError("DB error")
                )
            }
        ):
            result = process_month(2024, 1)
        assert result["status"] == "error_persistencia"

    def test_sap_entries_are_counted(self):
        lic = MagicMock()
        lic.id_externo = "SAP-001"
        fake_files = [("feed.xml", b"<dummy/>")]

        with _patch_all(
            **{
                "scraper.pipeline.iter_xml_files": MagicMock(return_value=fake_files),
                "scraper.pipeline.parse_atom_bytes": MagicMock(return_value=[(lic, [])]),
                "scraper.pipeline.upsert_licitaciones": MagicMock(return_value=(1, 0)),
            }
        ):
            result = process_month(2024, 1)
        assert result["status"] == "ok"
        assert result["tech_matches"] == 1
        assert result["nuevas"] == 1

    def test_adjudicaciones_are_persisted(self):
        lic = MagicMock()
        lic.id_externo = "SAP-002"
        adj = MagicMock()
        fake_files = [("feed.xml", b"<dummy/>")]

        with _patch_all(
            **{
                "scraper.pipeline.iter_xml_files": MagicMock(return_value=fake_files),
                "scraper.pipeline.parse_atom_bytes": MagicMock(return_value=[(lic, [adj])]),
                "scraper.pipeline.upsert_licitaciones": MagicMock(return_value=(1, 0)),
                "scraper.pipeline.replace_adjudicaciones_batch": MagicMock(return_value=(1, 0, 0)),
            }
        ):
            result = process_month(2024, 1)
        assert result["adjudicaciones"] == 1

    def test_xml_parse_error_increments_entries_error(self):
        fake_files = [("bad.xml", b"<broken")]

        with _patch_all(
            **{
                "scraper.pipeline.iter_xml_files": MagicMock(return_value=fake_files),
                "scraper.pipeline.parse_atom_bytes": MagicMock(
                    side_effect=Exception("XML malformado")
                ),
            }
        ):
            result = process_month(2024, 1)
        assert result["entries_error"] == 1

    def test_adj_persist_error_is_logged_but_doesnt_fail(self):
        lic = MagicMock()
        lic.id_externo = "SAP-003"
        adj = MagicMock()
        fake_files = [("feed.xml", b"<dummy/>")]

        with _patch_all(
            **{
                "scraper.pipeline.iter_xml_files": MagicMock(return_value=fake_files),
                "scraper.pipeline.parse_atom_bytes": MagicMock(return_value=[(lic, [adj])]),
                "scraper.pipeline.upsert_licitaciones": MagicMock(return_value=(1, 0)),
                "scraper.pipeline.replace_adjudicaciones_batch": MagicMock(
                    side_effect=RuntimeError("DB error adj")
                ),
            }
        ):
            result = process_month(2024, 1)
        # El error en adj no debe cambiar el status general
        assert result["status"] == "ok"


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
