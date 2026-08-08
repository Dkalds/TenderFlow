"""Tests para las mejoras implementadas: SSRF, scopes, RFC 7807, health liveness/readiness,
meta/filters, licitaciones/search, webhooks PATCH/ping/deliveries."""

from __future__ import annotations

from typing import ClassVar

import pytest
from fastapi.testclient import TestClient

# Fixtures api_db, api_key, client, auth se heredan de conftest.py


@pytest.fixture()
def admin_auth(api_db) -> dict[str, str]:
    """Credencial administrativa explícita para probar la validación de webhooks."""
    from api.auth import create_api_key
    from db.users import create_user, set_admin

    user_id = create_user(email="webhook-validation-admin@example.test", password_hash="not-used")
    set_admin(user_id, True)
    return {
        "X-API-Key": create_api_key(
            "webhook-validation-admin",
            scopes="*",
            user_id=user_id,
        )
    }


# ---------------------------------------------------------------------------
# Fase 1.1: SSRF en webhook URL
# ---------------------------------------------------------------------------


class TestWebhookSSRFValidation:
    """Los URLs privados/localhost deben rechazarse con 422."""

    _SSRF_URLS: ClassVar[list[str]] = [
        "http://127.0.0.1/steal-secrets",
        "http://localhost/steal-secrets",
        "http://192.168.1.1/internal",
        "http://10.0.0.1/internal",
        "http://169.254.169.254/latest/meta-data",  # AWS metadata
    ]

    def test_reject_localhost(self, client, admin_auth):
        resp = client.post(
            "/api/v1/webhooks",
            json={"name": "evil", "url": "http://localhost/steal", "event_types": ["*"]},
            headers=admin_auth,
        )
        assert resp.status_code == 422, f"Expected 422 for localhost, got {resp.status_code}"

    def test_reject_127_0_0_1(self, client, admin_auth):
        resp = client.post(
            "/api/v1/webhooks",
            json={"name": "evil", "url": "http://127.0.0.1/steal", "event_types": ["*"]},
            headers=admin_auth,
        )
        assert resp.status_code == 422

    def test_reject_private_network(self, client, admin_auth):
        resp = client.post(
            "/api/v1/webhooks",
            json={"name": "evil", "url": "http://192.168.1.1/internal", "event_types": ["*"]},
            headers=admin_auth,
        )
        assert resp.status_code == 422

    def test_reject_link_local(self, client, admin_auth):
        resp = client.post(
            "/api/v1/webhooks",
            json={"name": "evil", "url": "http://169.254.169.254/meta-data", "event_types": ["*"]},
            headers=admin_auth,
        )
        assert resp.status_code == 422

    def test_reject_no_scheme(self, client, admin_auth):
        resp = client.post(
            "/api/v1/webhooks",
            json={"name": "ok", "url": "ftp://example.com/hook", "event_types": ["*"]},
            headers=admin_auth,
        )
        assert resp.status_code == 422

    def test_reject_invalid_event_type(self, client, admin_auth):
        resp = client.post(
            "/api/v1/webhooks",
            json={"name": "ok", "url": "https://httpbin.org/post", "event_types": ["INVALID"]},
            headers=admin_auth,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Fase 1.5: Scopes en API keys
# ---------------------------------------------------------------------------


class TestApiKeyScopes:
    def test_wildcard_scope_allows_all(self, api_db, client):
        """Key con scope '*' puede acceder a todos los endpoints."""
        from api.auth import create_api_key

        wildcard_key = create_api_key("wildcard-reader", scopes="*")
        resp = client.get("/api/v1/licitaciones", headers={"X-API-Key": wildcard_key})
        assert resp.status_code == 200

    def test_restricted_scope_key_cannot_write_webhooks(self, api_db, client):
        """Key con scope 'licitaciones:read' no puede crear webhooks."""
        from api.auth import create_api_key

        raw = create_api_key("restricted", scopes="licitaciones:read")
        resp = client.post(
            "/api/v1/webhooks",
            json={"name": "x", "url": "https://httpbin.org/post", "event_types": ["*"]},
            headers={"X-API-Key": raw},
        )
        assert resp.status_code == 403

    def test_restricted_scope_can_read_licitaciones(self, api_db, client):
        """Key con scope 'licitaciones:read' puede leer licitaciones."""
        from api.auth import create_api_key

        raw = create_api_key("reader", scopes="licitaciones:read")
        resp = client.get("/api/v1/licitaciones", headers={"X-API-Key": raw})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Fase 4.3: RFC 7807 Problem Details
# ---------------------------------------------------------------------------


class TestRFC7807Errors:
    def test_401_has_problem_json_content_type(self, client):
        resp = client.get("/api/v1/licitaciones")
        assert resp.status_code == 401
        assert "problem+json" in resp.headers.get("content-type", "")

    def test_404_has_problem_json_structure(self, client, auth):
        resp = client.get("/api/v1/licitaciones/NO-EXISTE-JAMAS", headers=auth)
        assert resp.status_code == 404
        data = resp.json()
        assert "title" in data
        assert "status" in data
        assert data["status"] == 404

    def test_422_has_errors_field(self, client, auth):
        resp = client.get("/api/v1/licitaciones?limit=9999", headers=auth)
        assert resp.status_code == 422
        data = resp.json()
        assert "errors" in data or "detail" in data  # RFC 7807 ext. field

    def test_401_has_www_authenticate_header(self, client):
        resp = client.get("/api/v1/licitaciones")
        assert resp.status_code == 401
        assert "WWW-Authenticate" in resp.headers


# ---------------------------------------------------------------------------
# Fase 5.4: Health liveness/readiness split
# ---------------------------------------------------------------------------


class TestHealthEndpoints:
    def test_liveness_always_200(self, client):
        resp = client.get("/api/v1/health/live")
        assert resp.status_code == 200
        assert resp.json()["status"] == "alive"

    def test_readiness_200_when_db_ok(self, client):
        from unittest.mock import patch

        with (
            patch("api.routes.health._check_db", return_value="ok"),
            patch("api.routes.health._check_redis", return_value="unconfigured"),
            patch("api.routes.health._check_disk", return_value="ok"),
        ):
            resp = client.get("/api/v1/health/ready")
        assert resp.status_code == 200
        assert resp.json()["db"] == "ok"

    def test_readiness_responds_503_when_db_check_hangs(self, client, monkeypatch):
        """Una BD colgada da 503 "degraded", no un endpoint colgado.

        Sin techo de tiempo el sondeo espera al connect_timeout (10 s) o al
        statement_timeout (30 s) del pool: más de lo que aguanta el probe de la
        plataforma, que da el proceso por muerto y lo reinicia en vez de leer
        el estado degradado que este endpoint publica.
        """
        import time
        from unittest.mock import patch

        monkeypatch.setenv("HEALTH_CHECK_TIMEOUT_SECONDS", "0.2")

        def _hangs() -> str:
            time.sleep(5)
            return "ok"

        with (
            patch("api.routes.health._check_db", _hangs),
            patch("api.routes.health._check_redis", return_value="unconfigured"),
            patch("api.routes.health._check_disk", return_value="ok"),
        ):
            t0 = time.monotonic()
            resp = client.get("/api/v1/health/ready")
            elapsed = time.monotonic() - t0

        assert resp.status_code == 503
        assert resp.json()["db"] == "error"
        assert resp.json()["status"] == "degraded"
        assert elapsed < 4, f"el endpoint esperó al sondeo colgado ({elapsed:.1f}s)"

    def test_upstash_healthcheck_uses_pinned_https_transport(self, monkeypatch):
        from unittest.mock import MagicMock, patch

        from api.routes.health import _check_redis
        from config import settings

        monkeypatch.setattr(settings, "REDIS_URL", "rediss://:token@tenant.upstash.io:6379/0")
        monkeypatch.setattr(settings, "REDIS_REST_TOKEN", "")
        response = MagicMock()
        response.iter_content.return_value = iter([b'{"result":"PONG"}'])

        with patch("api.routes.health.pinned_https_request") as request:
            request.return_value.__enter__.return_value = response
            assert _check_redis() == "ok"

        request.assert_called_once_with(
            "GET",
            "https://tenant.upstash.io/PING",
            headers={"Authorization": "Bearer token"},
            timeout_seconds=5,
            allowed_hosts=frozenset({"tenant.upstash.io"}),
        )
        response.raise_for_status.assert_called_once()

    def test_health_alias_works(self, client):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200

    def test_liveness_no_auth(self, client):
        resp = client.get("/api/v1/health/live")
        assert resp.status_code != 401

    def test_readiness_no_auth(self, client):
        resp = client.get("/api/v1/health/ready")
        assert resp.status_code != 401


# ---------------------------------------------------------------------------
# Fase 4.3: /meta/filters
# ---------------------------------------------------------------------------


class TestMetaFilters:
    def test_filter_options_structure(self, client, auth):
        resp = client.get("/api/v1/meta/filters", headers=auth)
        assert resp.status_code == 200
        data = resp.json()
        assert "estado" in data
        assert "ccaa" in data
        assert "tecnologia" in data
        assert "cpv" in data

    def test_filter_options_are_lists(self, client, auth):
        data = client.get("/api/v1/meta/filters", headers=auth).json()
        for key in ["estado", "ccaa", "tecnologia", "cpv"]:
            assert isinstance(data[key], list)


# ---------------------------------------------------------------------------
# Fase 4.6: /licitaciones/search (POST)
# ---------------------------------------------------------------------------


class TestLicitacionesSearch:
    @pytest.fixture()
    def seeded(self, api_db, api_key):
        from db.database import connect

        with connect() as c:
            c.execute(
                "INSERT INTO licitaciones "
                "(id_externo, titulo, descripcion, organo_contratacion, importe, estado, "
                "fecha_publicacion, ccaa, cpv, url, tecnologia, fecha_extraccion) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                [
                    "S-001",
                    "SAP ERP AEAT",
                    "Implantación",
                    "AEAT",
                    500000.0,
                    "PUB",
                    "2025-01-15",
                    "Madrid",
                    "72000000",
                    "https://example.com/s001",
                    "SAP",
                    "2025-01-01",
                ],
            )
            c.execute(
                "INSERT INTO licitaciones "
                "(id_externo, titulo, organo_contratacion, importe, estado, "
                "fecha_publicacion, ccaa, tecnologia, fecha_extraccion) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                [
                    "S-002",
                    "Oracle Database Cataluña",
                    "Diputació",
                    120000.0,
                    "EV",
                    "2025-02-10",
                    "Cataluña",
                    "ORACLE",
                    "2025-02-01",
                ],
            )

        from api.app import app

        return TestClient(app), {"X-API-Key": api_key}

    def test_search_by_multiple_ccaa(self, seeded):
        client, auth = seeded
        resp = client.post(
            "/api/v1/licitaciones/search",
            json={"ccaa": ["Madrid", "Cataluña"], "with_total": True},
            headers=auth,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2

    def test_search_by_importe_range(self, seeded):
        client, auth = seeded
        resp = client.post(
            "/api/v1/licitaciones/search",
            json={"importe_min": 200000.0, "with_total": True},
            headers=auth,
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["id_externo"] == "S-001"

    def test_search_without_auth_returns_401(self, seeded):
        client, _ = seeded
        resp = client.post("/api/v1/licitaciones/search", json={})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Fase 3.4: ETag / Cache-Control en detalle de licitación
# ---------------------------------------------------------------------------


class TestETagCaching:
    @pytest.fixture()
    def lic_client(self, api_db, api_key):
        from db.database import connect

        with connect() as c:
            c.execute(
                "INSERT INTO licitaciones "
                "(id_externo, titulo, estado, ccaa, tecnologia, fecha_extraccion) "
                "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                ["ETAG-001", "SAP Test", "PUB", "Madrid", "SAP", "2025-01-01"],
            )
        from api.app import app

        return TestClient(app), {"X-API-Key": api_key}

    def test_detail_has_etag_header(self, lic_client):
        client, auth = lic_client
        resp = client.get("/api/v1/licitaciones/ETAG-001", headers=auth)
        assert resp.status_code == 200
        assert "ETag" in resp.headers

    def test_detail_has_cache_control(self, lic_client):
        client, auth = lic_client
        resp = client.get("/api/v1/licitaciones/ETAG-001", headers=auth)
        assert "Cache-Control" in resp.headers
        assert "private" in resp.headers["Cache-Control"]

    def test_if_none_match_returns_304(self, lic_client):
        client, auth = lic_client
        resp1 = client.get("/api/v1/licitaciones/ETAG-001", headers=auth)
        etag = resp1.headers["ETag"]
        resp2 = client.get(
            "/api/v1/licitaciones/ETAG-001",
            headers={**auth, "If-None-Match": etag},
        )
        assert resp2.status_code == 304


# ---------------------------------------------------------------------------
# Fase 2.1: Lifespan correctness
# ---------------------------------------------------------------------------


class TestLifespan:
    def test_app_starts_and_responds(self, client):
        """Con el lifespan nuevo, la app debe responder correctamente."""
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200

    def test_x_correlation_id_propagated(self, client):
        """La cabecera X-Correlation-Id se propaga en la respuesta."""
        resp = client.get("/api/v1/health", headers={"X-Correlation-Id": "test-123"})
        assert resp.headers.get("X-Correlation-Id") == "test-123"

    def test_x_correlation_id_generated(self, client):
        """Si no se envía X-Correlation-Id, se genera uno en la respuesta."""
        resp = client.get("/api/v1/health")
        assert "X-Correlation-Id" in resp.headers
        assert len(resp.headers["X-Correlation-Id"]) > 0


# ---------------------------------------------------------------------------
# Fase 4.4: Deprecation header en offset pagination
# ---------------------------------------------------------------------------


class TestDeprecationHeader:
    def test_offset_pagination_has_deprecation_header(self, client, auth):
        resp = client.get("/api/v1/licitaciones", headers=auth)
        assert resp.status_code == 200
        assert resp.headers.get("Deprecation") == "true"
        assert "Link" in resp.headers

    def test_cursor_pagination_no_deprecation_header(self, client, auth):
        resp = client.get("/api/v1/licitaciones/cursor", headers=auth)
        assert resp.status_code == 200
        assert "Deprecation" not in resp.headers


# ---------------------------------------------------------------------------
# Fase 3: with_total=false es más rápido (no incluye total)
# ---------------------------------------------------------------------------


class TestWithTotal:
    def test_with_total_false_returns_minus_one(self, client, auth):
        resp = client.get("/api/v1/licitaciones?with_total=false", headers=auth)
        assert resp.status_code == 200
        # total es -1 cuando with_total=false
        assert resp.json()["total"] == -1
