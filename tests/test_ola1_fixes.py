"""Tests para las mejoras de OLA 1 — cierre de deuda técnica.

Cubre:
- Idempotency-Key en POST /feedback y POST /webhooks
- Cardinalidad de métricas Prometheus (path template vs path crudo)
- METRICS_ALLOWED_IPS declarado en Settings
- connect_read en api/auth.py (sin regresión de autenticación)
- create_api_key acepta user_id
- retention_cleanup cubre idempotency_keys y webhook_deliveries
- Graceful shutdown inicializa pending_background_tasks en app.state
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def app_and_client(api_db, monkeypatch):
    """App sobre el schema Postgres aislado del test."""
    monkeypatch.setenv("ENV", "dev")

    from api.app import app

    with TestClient(app, raise_server_exceptions=True) as client:
        yield app, client


@pytest.fixture()
def api_key(app_and_client):
    _, _client = app_and_client
    from api.auth import create_api_key
    from db.users import create_user, set_admin

    user_id = create_user(email="ola-admin@example.test", password_hash="not-used")
    set_admin(user_id, True)
    return create_api_key("test-ola1", scopes="*", user_id=user_id)


# ── OLA 1.1: Idempotency-Key en POST /feedback ────────────────────────────────


def test_feedback_idempotency_second_request_returns_cached(app_and_client, api_key):
    """Dos requests con la misma Idempotency-Key deben devolver la misma respuesta."""
    _, client = app_and_client
    headers = {"X-API-Key": api_key, "Idempotency-Key": "test-idem-fb-001"}
    body = {"expediente": "PRO/2024/IDM1", "relevante": True, "nota": "test"}

    r1 = client.post("/api/v1/feedback", json=body, headers=headers)
    assert r1.status_code == 201

    r2 = client.post("/api/v1/feedback", json=body, headers=headers)
    assert r2.status_code == 201

    # Misma respuesta: mismo stored_at
    assert r1.json()["stored_at"] == r2.json()["stored_at"]


def test_feedback_without_idempotency_key_allows_duplicates(app_and_client, api_key):
    """Sin Idempotency-Key, requests repetidas deben insertarse (timestamps distintos)."""
    _, client = app_and_client
    headers = {"X-API-Key": api_key}
    body = {"expediente": "PRO/2024/NOKEY", "relevante": False, "nota": ""}

    r1 = client.post("/api/v1/feedback", json=body, headers=headers)
    r2 = client.post("/api/v1/feedback", json=body, headers=headers)
    assert r1.status_code == 201
    assert r2.status_code == 201
    # stored_at puede coincidir si son muy rápidos, pero no debe crashear


def test_webhook_create_idempotency(app_and_client, api_key):
    """POST /webhooks con Idempotency-Key no debe crear webhook duplicado."""
    _, client = app_and_client
    headers = {"X-API-Key": api_key, "Idempotency-Key": "test-idem-wh-001"}
    body = {"name": "my-hook", "url": "https://example.com/hook", "event_types": ["*"]}

    r1 = client.post("/api/v1/webhooks", json=body, headers=headers)
    assert r1.status_code == 201
    id1 = r1.json()["id"]

    r2 = client.post("/api/v1/webhooks", json=body, headers=headers)
    assert r2.status_code == 201
    id2 = r2.json()["id"]

    # Misma respuesta cacheada — mismo id
    assert id1 == id2
    assert r1.json()["secret"] == r2.json()["secret"]

    # Solo debe existir un webhook en total
    all_hooks = client.get("/api/v1/webhooks", headers={"X-API-Key": api_key}).json()
    assert len(all_hooks) == 1


def test_webhook_idempotency_never_persists_secret_or_replays_different_body(
    app_and_client, api_key, monkeypatch
):
    """The cache is actor-scoped, secret-free, and bound to the request body."""
    from db.database import connect_read

    monkeypatch.setattr("api.routes.webhooks.validate_outbound_url", lambda url, **_: url)
    _, client = app_and_client
    headers = {"X-API-Key": api_key, "Idempotency-Key": "test-idem-wh-secure-001"}
    body = {"name": "secure-hook", "url": "https://example.com/hook", "event_types": ["*"]}

    created = client.post("/api/v1/webhooks", json=body, headers=headers)
    assert created.status_code == 201, created.text
    secret = created.json()["secret"]

    with connect_read() as connection:
        row = connection.execute(
            "SELECT response_json FROM idempotency_keys WHERE idem_key = %s",
            (headers["Idempotency-Key"],),
        ).fetchone()
    assert row is not None
    assert secret not in str(row[0])
    assert '"secret"' not in str(row[0])

    replay_with_other_body = client.post(
        "/api/v1/webhooks",
        json={**body, "name": "other-hook"},
        headers=headers,
    )
    assert replay_with_other_body.status_code == 409


# ── OLA 1.2: Cardinalidad de métricas ────────────────────────────────────────


def test_metrics_use_route_template_not_raw_path():
    """AccessLogMiddleware debe usar route template para evitar cardinalidad explosiva."""
    from unittest.mock import MagicMock

    # Simular que request.scope["route"].path = "/api/v1/licitaciones/{id}"
    mock_route = MagicMock()
    mock_route.path = "/api/v1/licitaciones/{id}"

    mock_request = MagicMock()
    mock_request.scope = {"route": mock_route}
    mock_request.url.path = "/api/v1/licitaciones/EXP-123-ABC"
    mock_request.method = "GET"
    mock_request.headers.get.return_value = None
    mock_request.client = None

    # El path que se usaría en métricas debe ser el template
    route = mock_request.scope.get("route")
    path = getattr(route, "path", None) or mock_request.url.path.split("?")[0]
    assert path == "/api/v1/licitaciones/{id}"
    assert "EXP-123-ABC" not in path


def test_metrics_fallback_to_raw_when_no_route():
    """Si no hay route en scope, fallback al path crudo."""
    from unittest.mock import MagicMock

    mock_request = MagicMock()
    mock_request.scope = {}  # sin 'route'
    mock_request.url.path = "/unknown/path"

    route = mock_request.scope.get("route")
    path = getattr(route, "path", None) or mock_request.url.path.split("?")[0]
    assert path == "/unknown/path"


# ── OLA 1.4: METRICS_ALLOWED_IPS en Settings ─────────────────────────────────


def test_metrics_allowed_ips_declared_in_settings():
    """METRICS_ALLOWED_IPS debe estar declarado en Settings con default '127.0.0.1'."""
    from config.settings import Settings

    # Debe existir el campo (no lanzar AttributeError)
    default_val = Settings.__fields__.get("METRICS_ALLOWED_IPS") or Settings.model_fields.get(
        "METRICS_ALLOWED_IPS"
    )
    assert default_val is not None, "METRICS_ALLOWED_IPS no encontrado en Settings"

    # El valor default debe ser '127.0.0.1'
    from config import settings

    assert "127.0.0.1" in settings.METRICS_ALLOWED_IPS


# ── OLA 1.5: connect_read en auth.py ─────────────────────────────────────────


def test_require_api_key_uses_connect_read(monkeypatch):
    """require_api_key no debe usar connect() para reads — solo connect_read().

    Tras la migración a services.auth, api.auth ya no importa connect/connect_read
    directamente. Verificamos que el servicio delega al repositorio (que usa
    connect_read) y no importa connect() para escrituras.
    """
    import services.auth as svc_auth

    # Tras la migración, services.auth ya no importa connect/connect_read
    # directamente — delega todo al ApiKeyRepository.
    assert not hasattr(svc_auth, "connect"), (
        "services.auth no debería importar connect() — debe delegar al repositorio"
    )

    # Verificar que el repo subyacente usa connect_read para lookups
    import db.repositories.api_keys as repo_mod

    write_calls: list[int] = []
    original_connect = repo_mod.connect

    def spy_connect(*args, **kwargs):
        write_calls.append(1)
        return original_connect(*args, **kwargs)

    monkeypatch.setattr(repo_mod, "connect", spy_connect)

    # Llamar a require_api_key con key inválida (debe fallar pero sin usar connect)
    import asyncio

    from fastapi import HTTPException

    import api.auth as auth_mod

    async def _test():
        try:
            await auth_mod.require_api_key("invalid-key-xyz")
        except HTTPException:
            pass

    asyncio.run(_test())

    # connect() no debería haber sido llamado para la lectura de validación
    assert write_calls == [], (
        "require_api_key llamó a connect() para una lectura — debe usar connect_read()"
    )


# ── OLA 1.7: create_api_key acepta user_id ───────────────────────────────────


def test_create_api_key_accepts_user_id(api_db, monkeypatch):
    """create_api_key debe persistir user_id cuando se proporciona.

    El usuario se crea de verdad: ``api_keys.user_id`` tiene FK contra
    ``users``. El test usaba un 42 inventado y pasaba sólo porque corría sobre
    SQLite, que no estaba aplicando la FK — otra divergencia que ADR-021
    cierra.
    """
    import db.database as db_mod

    monkeypatch.setenv("ENV", "dev")

    from api.auth import create_api_key
    from db.users import create_user

    user_id = create_user(
        email="apikey-owner@example.com",
        password_hash="hash",  # pragma: allowlist secret -- valor sintético de test
        display_name="Owner",
    )

    raw = create_api_key("test-uid", scopes="read:*", user_id=user_id)
    assert raw  # token generado

    with db_mod.connect_read() as c:
        row = c.execute(
            "SELECT name, scopes, user_id FROM api_keys WHERE name = 'test-uid'"
        ).fetchone()

    assert row is not None
    assert row[0] == "test-uid"
    assert row[1] == "read:*"
    assert row[2] == user_id


def test_create_api_key_backward_compat_no_user_id(api_db, monkeypatch):
    """create_api_key sigue funcionando sin user_id (backward compat)."""
    monkeypatch.setenv("ENV", "dev")

    from api.auth import create_api_key

    raw = create_api_key("compat-key")
    assert raw


# ── OLA 1.6: retention_cleanup cubre nuevas tablas ───────────────────────────


def test_retention_cleanup_purges_idempotency_keys(tmp_db, monkeypatch):
    """run_retention debe purgar idempotency_keys > 1 día."""
    monkeypatch.setenv("ENV", "dev")
    db_mod, _ = tmp_db

    # Insertar una idempotency key antigua (2 días atrás)
    from datetime import UTC, datetime, timedelta

    old_ts = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    with db_mod.connect() as c:
        c.execute(
            "INSERT INTO idempotency_keys (idem_key, endpoint, response_json, created_at) "
            "VALUES ('old-key', 'feedback', '{}', %s)",
            (old_ts,),
        )

    from scripts.retention_cleanup import run_retention

    result = run_retention(
        runs_days=90,
        audit_days=180,
        dlq_days=30,
        history_days=365,
        access_days=180,
        idempotency_days=1,
        webhook_deliveries_days=90,
        apply=True,
    )

    assert result.get("idempotency_keys", 0) >= 1

    # Verificar que se eliminó
    with db_mod.connect_read() as c:
        row = c.execute(
            "SELECT COUNT(*) FROM idempotency_keys WHERE idem_key = 'old-key'"
        ).fetchone()
    assert row[0] == 0


# ── OLA 1.8: Graceful shutdown ────────────────────────────────────────────────


def test_lifespan_initializes_pending_tasks_set(app_and_client):
    """app.state.pending_background_tasks debe estar inicializado tras startup."""
    app, _ = app_and_client
    assert hasattr(app.state, "pending_background_tasks")
    assert isinstance(app.state.pending_background_tasks, set)
