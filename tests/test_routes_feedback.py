"""Tests para api/routes/feedback.py — submit, stats y queue (mocks de repositorio)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestFeedbackEndpoints:
    """Cover feedback.py uncovered lines."""

    @patch("api.routes.feedback.log_event")
    @patch("api.routes.feedback._repo")
    def test_submit_feedback_db_error(self, mock_repo, mock_log, client, auth):
        mock_repo.exists_idempotency = MagicMock(return_value=None)
        mock_repo.insert = MagicMock(side_effect=RuntimeError("db error"))
        resp = client.post(
            "/api/v1/feedback",
            json={"expediente": "EXP/001", "relevante": True, "nota": "test"},
            headers=auth,
        )
        assert resp.status_code == 500

    @patch("api.routes.feedback.log_event")
    @patch("api.routes.feedback._repo")
    def test_submit_feedback_success(self, mock_repo, mock_log, client, auth):
        mock_repo.exists_idempotency = MagicMock(return_value=None)
        mock_repo.insert = MagicMock(return_value="2024-01-01T00:00:00Z")
        mock_repo.store_idempotency = MagicMock()
        resp = client.post(
            "/api/v1/feedback",
            json={"expediente": "EXP/001", "relevante": True, "nota": ""},
            headers=auth,
        )
        assert resp.status_code == 201
        assert resp.json()["status"] == "ok"

    @patch("api.routes.feedback._repo")
    def test_feedback_stats(self, mock_repo, client, auth):
        # Las claves son las que devuelve FeedbackRepository.stats y las que
        # exige el DTO FeedbackStats; el mock antiguo (`relevant`) no coincidía
        # con ninguno de los dos y solo pasaba porque la respuesta era un dict
        # sin tipar.
        mock_repo.stats = MagicMock(
            return_value={
                "total": 5,
                "positivos": 3,
                "negativos": 2,
                "last_feedback_at": "2026-01-01T00:00:00Z",
            }
        )
        resp = client.get("/api/v1/feedback/stats", headers=auth)
        assert resp.status_code == 200
        assert resp.json() == {
            "total": 5,
            "positivos": 3,
            "negativos": 2,
            "last_feedback_at": "2026-01-01T00:00:00Z",
        }

    @patch("api.routes.feedback._lic_repo")
    def test_feedback_queue_random(self, mock_lic, client, auth):
        mock_lic.get_unlabelled_random = MagicMock(return_value=[{"id_externo": "x"}])
        resp = client.get("/api/v1/feedback/queue?strategy=random&limit=5", headers=auth)
        assert resp.status_code == 200
        assert resp.json()["strategy"] == "random"

    @patch("api.routes.feedback._lic_repo")
    def test_feedback_queue_uncertainty_no_candidates(self, mock_lic, client, auth):
        mock_lic.get_unlabelled_candidates = MagicMock(return_value=[])
        resp = client.get("/api/v1/feedback/queue?strategy=uncertainty", headers=auth)
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["strategy"] == "uncertainty"

    @patch("api.routes.feedback._lic_repo")
    def test_feedback_queue_uncertainty_with_candidates(self, mock_lic, client, auth):
        candidates = [
            {"id_externo": "A", "titulo": "SAP project", "descripcion": "desc"},
            {"id_externo": "B", "titulo": "Other project", "descripcion": ""},
        ]
        mock_lic.get_unlabelled_candidates = MagicMock(return_value=candidates)

        import numpy as np

        fake_probs = np.array([[0.3, 0.7], [0.5, 0.5]])
        mock_clf = MagicMock()
        mock_clf.predict_proba.return_value = fake_probs

        with patch("scraper.ml_classifier.SAPClassifier.load", return_value=mock_clf):
            resp = client.get("/api/v1/feedback/queue?strategy=uncertainty&limit=10", headers=auth)
        assert resp.status_code == 200
        data = resp.json()
        assert data["strategy"] == "uncertainty"
        assert len(data["items"]) <= 10

    @patch("api.routes.feedback._lic_repo")
    def test_feedback_queue_uncertainty_exception_fallback(self, mock_lic, client, auth):
        mock_lic.get_unlabelled_candidates = MagicMock(side_effect=RuntimeError("fail"))
        mock_lic.get_unlabelled_random = MagicMock(return_value=[])
        resp = client.get("/api/v1/feedback/queue?strategy=uncertainty", headers=auth)
        assert resp.status_code == 200
        assert resp.json()["strategy"] == "random"
