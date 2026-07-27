"""Tests for /api/v1/feedback/queue — model block with tech_scores."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def seeded_db(api_db):
    from api.auth import create_api_key
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, descripcion, organo_contratacion, importe, estado, "
            "fecha_publicacion, ccaa, cpv, url, tecnologia, ml_tecnologias, "
            "ml_proba_max, ml_tech_principal, fecha_extraccion) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
            [
                "Q-001",
                "Sistema SAP ERP para AEAT",
                "Implantacion SAP S/4HANA Cloud para gestion financiera",
                "AEAT",
                500000.0,
                "PUB",
                "2025-01-15",
                "Madrid",
                "72000000",
                "https://example.com/q/001",
                "SAP",
                '["SAP"]',
                0.82,
                "SAP",
                "2025-01-01",
            ],
        )
        c.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, descripcion, organo_contratacion, importe, estado, "
            "fecha_publicacion, ccaa, cpv, url, tecnologia, ml_tecnologias, "
            "ml_proba_max, ml_tech_principal, fecha_extraccion) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
            [
                "Q-002",
                "CRM Salesforce para Comunidad de Madrid",
                "Implementacion Salesforce Service Cloud",
                "Comunidad de Madrid",
                250000.0,
                "PUB",
                "2025-02-10",
                "Madrid",
                "72212000",
                "https://example.com/q/002",
                "SALESFORCE",
                '["SALESFORCE","SAP"]',
                0.65,
                "SALESFORCE",
                "2025-02-01",
            ],
        )
        c.commit()

    from api.app import app

    client = TestClient(app, raise_server_exceptions=True)
    client._api_key = create_api_key("feedback-reader", scopes="feedback:read")
    return client


def _auth(seeded_db):
    return {"X-API-Key": seeded_db._api_key}


class TestFeedbackQueueContextFields:
    def test_queue_returns_context_fields(self, seeded_db):
        resp = seeded_db.get(
            "/api/v1/feedback/queue?strategy=random&limit=10", headers=_auth(seeded_db)
        )
        assert resp.status_code == 200
        data = resp.json()
        items = data.get("items", [])
        if items:
            item = items[0]
            assert "descripcion" in item
            assert "cpv" in item
            assert "importe" in item
            assert "organo" in item
            assert "ccaa" in item
            assert "fecha_publicacion" in item
            assert "url_origen" in item

    def test_queue_descripcion_truncated_500(self, seeded_db):
        resp = seeded_db.get(
            "/api/v1/feedback/queue?strategy=random&limit=10", headers=_auth(seeded_db)
        )
        assert resp.status_code == 200
        items = resp.json().get("items", [])
        for item in items:
            if item.get("descripcion"):
                assert len(item["descripcion"]) <= 500

    def test_queue_importe_is_number_or_null(self, seeded_db):
        resp = seeded_db.get(
            "/api/v1/feedback/queue?strategy=random&limit=10", headers=_auth(seeded_db)
        )
        assert resp.status_code == 200
        items = resp.json().get("items", [])
        for item in items:
            if item.get("importe") is not None:
                assert isinstance(item["importe"], (int, float))


class TestFeedbackQueueModelBlock:
    def test_model_block_present_when_tech_classifier_unavailable(self, seeded_db, monkeypatch):
        monkeypatch.setattr(
            "scraper.tech_classifier.TechnologyClassifier.is_available",
            classmethod(lambda cls, path=None: False),
        )
        resp = seeded_db.get(
            "/api/v1/feedback/queue?strategy=random&limit=10", headers=_auth(seeded_db)
        )
        assert resp.status_code == 200
        items = resp.json().get("items", [])
        for item in items:
            assert item.get("model") is None

    def test_model_block_has_expected_keys(self, seeded_db, monkeypatch):
        from scraper.tech_classifier import TechnologyClassifier

        class _FakeClassifier:
            labels = TechnologyClassifier.labels if hasattr(TechnologyClassifier, "labels") else []

            def predict_batch(self, items):
                return [
                    {
                        "scores": {
                            "SAP": 0.72,
                            "SALESFORCE": 0.10,
                            "ORACLE": 0.05,
                            "MICROSOFT": 0.03,
                            "SERVICENOW": 0.0,
                            "WORKDAY": 0.0,
                            "IBM": 0.0,
                            "OPENTEXT": 0.0,
                            "UNIT4": 0.0,
                            "META4": 0.0,
                            "SOPRA": 0.0,
                            "SAGE": 0.0,
                            "INFOR": 0.0,
                        },
                        "predicted": ["SAP"],
                        "principal": "SAP",
                        "max_proba": 0.72,
                        "thresholds": {
                            "SAP": 0.5,
                            "SALESFORCE": 0.5,
                            "ORACLE": 0.5,
                            "MICROSOFT": 0.5,
                            "SERVICENOW": 0.5,
                            "WORKDAY": 0.5,
                            "IBM": 0.5,
                            "OPENTEXT": 0.5,
                            "UNIT4": 0.5,
                            "META4": 0.5,
                            "SOPRA": 0.5,
                            "SAGE": 0.5,
                            "INFOR": 0.5,
                        },
                    }
                    for _ in items
                ]

        monkeypatch.setattr(
            "scraper.tech_classifier.TechnologyClassifier.is_available",
            classmethod(lambda cls, path=None: True),
        )
        monkeypatch.setattr(
            "scraper.tech_classifier.TechnologyClassifier.load",
            classmethod(lambda cls, path=None: _FakeClassifier()),
        )

        resp = seeded_db.get(
            "/api/v1/feedback/queue?strategy=random&limit=10", headers=_auth(seeded_db)
        )
        assert resp.status_code == 200
        items = resp.json().get("items", [])
        for item in items:
            model = item.get("model")
            if model is not None:
                assert "tech_scores" in model
                assert "tech_predicted" in model
                assert "tech_principal" in model
                assert "tech_max_proba" in model
                assert "tech_thresholds" in model

    def test_tech_scores_sums_positive(self, seeded_db, monkeypatch):
        class _FakeClf:
            def predict_batch(self, items):
                return [
                    {
                        "scores": {"SAP": 0.72, "SALESFORCE": 0.10},
                        "predicted": ["SAP"],
                        "principal": "SAP",
                        "max_proba": 0.72,
                        "thresholds": {"SAP": 0.5, "SALESFORCE": 0.6},
                    }
                    for _ in items
                ]

        monkeypatch.setattr(
            "scraper.tech_classifier.TechnologyClassifier.is_available",
            classmethod(lambda cls, path=None: True),
        )
        monkeypatch.setattr(
            "scraper.tech_classifier.TechnologyClassifier.load",
            classmethod(lambda cls, path=None: _FakeClf()),
        )

        resp = seeded_db.get(
            "/api/v1/feedback/queue?strategy=random&limit=10", headers=_auth(seeded_db)
        )
        assert resp.status_code == 200
        items = resp.json().get("items", [])
        for item in items:
            model = item.get("model")
            if model is not None:
                total = sum(model["tech_scores"].values())
                assert total > 0

    def test_tech_scores_rounded_3_decimals(self, seeded_db, monkeypatch):
        class _FakeClf:
            def predict_batch(self, items):
                return [
                    {
                        "scores": {"SAP": 0.723456, "SALESFORCE": 0.101111},
                        "predicted": ["SAP"],
                        "principal": "SAP",
                        "max_proba": 0.723456,
                        "thresholds": {"SAP": 0.5, "SALESFORCE": 0.6},
                    }
                    for _ in items
                ]

        monkeypatch.setattr(
            "scraper.tech_classifier.TechnologyClassifier.is_available",
            classmethod(lambda cls, path=None: True),
        )
        monkeypatch.setattr(
            "scraper.tech_classifier.TechnologyClassifier.load",
            classmethod(lambda cls, path=None: _FakeClf()),
        )

        resp = seeded_db.get(
            "/api/v1/feedback/queue?strategy=random&limit=10", headers=_auth(seeded_db)
        )
        assert resp.status_code == 200
        items = resp.json().get("items", [])
        for item in items:
            model = item.get("model")
            if model is not None:
                for score in model["tech_scores"].values():
                    assert score == round(score, 3)
