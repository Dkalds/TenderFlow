"""Tests para scheduler/concept_drift.py — detección de concept drift."""

from __future__ import annotations

from unittest.mock import patch


class TestTokenize:
    def test_basic_tokens(self):
        from scheduler.concept_drift import _tokenize

        tokens = _tokenize("SAP S/4HANA migración cloud")
        assert "sap" in tokens
        assert "s/4hana" in tokens
        assert "cloud" in tokens

    def test_filters_stop_words(self):
        from scheduler.concept_drift import _tokenize

        tokens = _tokenize("el servicio de contrato para la gestión")
        # All words should be stop words
        assert len(tokens) == 0

    def test_short_words_excluded(self):
        from scheduler.concept_drift import _tokenize

        tokens = _tokenize("ab cd ef sap")
        assert "sap" in tokens
        assert "ab" not in tokens


class TestDetectDrift:
    def _mock_texts(self):
        return [
            "Implementación SAP S/4HANA y migración a kubernetes cloud",
            "Soporte SAP con integración terraform automatización",
            "Consultoría SAP con devops kubernetes infraestructura",
            "Desarrollo SAP y kubernetes contenedores microservicios",
        ]

    @patch("scheduler.concept_drift._fetch_recent_texts")
    def test_detects_unknown_terms(self, mock_fetch):
        from scheduler.concept_drift import detect_drift

        mock_fetch.return_value = self._mock_texts()
        candidates = detect_drift(days=30, min_doc_freq=2, top_n=10)

        terms = [c["term"] for c in candidates]
        # "kubernetes" appears in 3 docs and is NOT in SAP_KEYWORDS
        assert "kubernetes" in terms

    @patch("scheduler.concept_drift._fetch_recent_texts")
    def test_excludes_known_terms(self, mock_fetch):
        from scheduler.concept_drift import detect_drift

        mock_fetch.return_value = self._mock_texts()
        candidates = detect_drift(days=30, min_doc_freq=1, top_n=50)

        terms = [c["term"] for c in candidates]
        # "sap" is in SAP_KEYWORDS, should be excluded
        assert "sap" not in terms

    @patch("scheduler.concept_drift._fetch_recent_texts")
    def test_empty_texts(self, mock_fetch):
        from scheduler.concept_drift import detect_drift

        mock_fetch.return_value = []
        candidates = detect_drift(days=30)
        assert candidates == []

    @patch("scheduler.concept_drift._fetch_recent_texts")
    def test_top_n_limits(self, mock_fetch):
        from scheduler.concept_drift import detect_drift

        mock_fetch.return_value = self._mock_texts()
        candidates = detect_drift(days=30, min_doc_freq=1, top_n=2)
        assert len(candidates) <= 2

    @patch("scheduler.concept_drift._fetch_recent_texts")
    def test_doc_freq_returned(self, mock_fetch):
        from scheduler.concept_drift import detect_drift

        mock_fetch.return_value = self._mock_texts()
        candidates = detect_drift(days=30, min_doc_freq=2, top_n=10)
        for c in candidates:
            assert c["doc_freq"] >= 2
            assert isinstance(c["example_titles"], list)


class TestRunDriftReport:
    @patch("scheduler.concept_drift.notify")
    @patch("scheduler.concept_drift._fetch_recent_texts")
    def test_sends_alert(self, mock_fetch, mock_notify):
        from scheduler.concept_drift import run_drift_report

        mock_fetch.return_value = [
            "Implementación SAP kubernetes cloud native",
            "Migración SAP kubernetes microservicios",
            "Soporte SAP kubernetes devops pipeline",
        ]
        result = run_drift_report(days=30, send_alert=True)
        if result:
            mock_notify.assert_called_once()

    @patch("scheduler.concept_drift.notify")
    @patch("scheduler.concept_drift._fetch_recent_texts")
    def test_no_alert_when_empty(self, mock_fetch, mock_notify):
        from scheduler.concept_drift import run_drift_report

        mock_fetch.return_value = []
        result = run_drift_report(days=30, send_alert=True)
        assert result == []
        mock_notify.assert_not_called()
