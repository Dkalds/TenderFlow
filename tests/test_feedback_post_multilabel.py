"""Tests for POST /api/v1/feedback — multi-tecnologia label support."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def fb_client(api_db):
    from api.app import app
    from api.auth import create_api_key
    from db.users import create_user

    client = TestClient(app, raise_server_exceptions=True)
    user_id = create_user(email="feedback-writer@example.test", password_hash="not-used")
    client._api_key = create_api_key(
        "feedback-writer",
        scopes="feedback:write",
        user_id=user_id,
    )
    return client


def _auth(fb_client):
    return {"X-API-Key": fb_client._api_key}


class TestFeedbackPostMultilabel:
    def test_post_with_tecnologia(self, fb_client):
        resp = fb_client.post(
            "/api/v1/feedback",
            json={
                "expediente": "MULTI-001",
                "relevante": True,
                "tecnologia": "SAP",
            },
            headers=_auth(fb_client),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "ok"
        assert data["expediente"] == "MULTI-001"

    def test_post_with_secundarias(self, fb_client):
        resp = fb_client.post(
            "/api/v1/feedback",
            json={
                "expediente": "MULTI-002",
                "relevante": True,
                "tecnologia": "SAP",
                "tecnologias_secundarias": ["MICROSOFT", "INFOR"],
            },
            headers=_auth(fb_client),
        )
        assert resp.status_code == 201

    def test_post_invalid_tecnologia_422(self, fb_client):
        resp = fb_client.post(
            "/api/v1/feedback",
            json={
                "expediente": "MULTI-003",
                "relevante": True,
                "tecnologia": "INVALID_TECH",
            },
            headers=_auth(fb_client),
        )
        assert resp.status_code == 422

    def test_post_invalid_secundaria_422(self, fb_client):
        resp = fb_client.post(
            "/api/v1/feedback",
            json={
                "expediente": "MULTI-004",
                "relevante": True,
                "tecnologia": "SAP",
                "tecnologias_secundarias": ["SAP", "BOGUS"],
            },
            headers=_auth(fb_client),
        )
        assert resp.status_code == 422

    def test_post_tecnologia_null_ok(self, fb_client):
        resp = fb_client.post(
            "/api/v1/feedback",
            json={
                "expediente": "MULTI-005",
                "relevante": False,
                "tecnologia": None,
            },
            headers=_auth(fb_client),
        )
        assert resp.status_code == 201

    def test_post_backward_compat_no_tecnologia(self, fb_client):
        resp = fb_client.post(
            "/api/v1/feedback",
            json={
                "expediente": "MULTI-006",
                "relevante": True,
                "nota": "sin tecnologia",
            },
            headers=_auth(fb_client),
        )
        assert resp.status_code == 201

    def test_tecnologia_normalized_uppercase(self, fb_client, api_db):
        resp = fb_client.post(
            "/api/v1/feedback",
            json={
                "expediente": "MULTI-007",
                "relevante": True,
                "tecnologia": "sap",
            },
            headers=_auth(fb_client),
        )
        assert resp.status_code == 201

        from db.database import connect_read

        with connect_read() as c:
            row = c.execute(
                "SELECT tecnologia FROM ml_feedback WHERE expediente = ?",
                ("MULTI-007",),
            ).fetchone()
        assert row is not None
        assert row[0] == "SAP"

    def test_secundarias_persisted_as_json(self, fb_client, api_db):
        fb_client.post(
            "/api/v1/feedback",
            json={
                "expediente": "MULTI-008",
                "relevante": True,
                "tecnologia": "SAP",
                "tecnologias_secundarias": ["MICROSOFT", "INFOR"],
            },
            headers=_auth(fb_client),
        )

        from db.database import connect_read

        with connect_read() as c:
            row = c.execute(
                "SELECT tecnologia, tecnologias_secundarias FROM ml_feedback WHERE expediente = ?",
                ("MULTI-008",),
            ).fetchone()
        assert row is not None
        assert row[0] == "SAP"
        parsed = json.loads(row[1])
        assert "MICROSOFT" in parsed
        assert "INFOR" in parsed

    def test_secundarias_normalized_uppercase(self, fb_client, api_db):
        fb_client.post(
            "/api/v1/feedback",
            json={
                "expediente": "MULTI-009",
                "relevante": True,
                "tecnologia": "oracle",
                "tecnologias_secundarias": ["microsoft"],
            },
            headers=_auth(fb_client),
        )

        from db.database import connect_read

        with connect_read() as c:
            row = c.execute(
                "SELECT tecnologia, tecnologias_secundarias FROM ml_feedback WHERE expediente = ?",
                ("MULTI-009",),
            ).fetchone()
        assert row is not None
        assert row[0] == "ORACLE"
        parsed = json.loads(row[1])
        assert parsed == ["MICROSOFT"]

    def test_not_relevant_with_null_tecnologia(self, fb_client, api_db):
        fb_client.post(
            "/api/v1/feedback",
            json={
                "expediente": "MULTI-010",
                "relevante": False,
            },
            headers=_auth(fb_client),
        )

        from db.database import connect_read

        with connect_read() as c:
            row = c.execute(
                "SELECT relevante, tecnologia, tecnologias_secundarias FROM ml_feedback WHERE expediente = ?",
                ("MULTI-010",),
            ).fetchone()
        assert row is not None
        assert row[0] == 0
        assert row[1] is None
