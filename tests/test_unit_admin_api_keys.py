"""Tests para api/routes/admin_api_keys.py — las claves de toda la instancia.

Sin base de datos: el repositorio y la auditoría se sustituyen. Lo que se fija
es el contrato (solo administradores, nada de hash ni token, el recuento viene
del servidor) y que revocar audita con el ``users.id`` de quien actúa.
El recorrido contra Postgres está en ``tests/test_admin_api_keys_route.py``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from api.app import app
from api.routes.dual_auth import require_any_auth


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    return TestClient(app)


def _admin() -> dict[str, Any]:
    return {"user_id": 1, "email": "admin@test.com", "is_admin": True, "auth_method": "session"}


def _no_admin() -> dict[str, Any]:
    return {"user_id": 2, "email": "user@test.com", "is_admin": False, "auth_method": "session"}


_FILAS = [
    {
        "id": 10,
        "name": "integración CRM",
        "prefix": "abcdefgh",
        "tier": "free",
        "scopes": "data:read",
        "user_id": 5,
        "owner_email": "ana@example.test",
        "owner_name": "Ana",
        "owner_deactivated": False,
        "organization_id": None,
        "created_at": "2026-10-01T10:00:00+00:00",
        "expires_at": "2026-12-30T10:00:00+00:00",
        "last_used": "2026-10-20T08:00:00+00:00",
        "is_active": 1,
        "estado": "activa",
    },
    {
        "id": 3,
        "name": "legacy",
        "prefix": None,
        "tier": "free",
        "scopes": "*",
        "user_id": None,
        "owner_email": None,
        "owner_name": None,
        "owner_deactivated": False,
        "organization_id": None,
        "created_at": "2026-05-01T10:00:00+00:00",
        "expires_at": None,
        "last_used": None,
        "is_active": 1,
        "estado": "activa",
    },
]

_RESUMEN = {"total": 4, "activas": 2, "activas_sin_dueno": 1, "activas_sin_caducidad": 1}


def test_listar_exige_admin(client):
    app.dependency_overrides[require_any_auth] = _no_admin
    try:
        resp = client.get("/api/v1/admin/api-keys")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 403


def test_listar_devuelve_dueno_y_resumen_sin_secretos(client):
    app.dependency_overrides[require_any_auth] = _admin
    try:
        with (
            patch("api.routes.admin_api_keys._repo.list_all", return_value=_FILAS) as listar,
            patch("api.routes.admin_api_keys._repo.resumen_instancia", return_value=_RESUMEN),
        ):
            resp = client.get("/api/v1/admin/api-keys", params={"limit": 2})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    listar.assert_called_once_with(limit=2)
    cuerpo = resp.json()
    assert cuerpo["resumen"] == _RESUMEN
    # 4 en la tabla, 2 en la página: la UI tiene que poder decirlo.
    assert cuerpo["truncado"] is True
    con_dueno, sin_dueno = cuerpo["items"]
    assert con_dueno["owner_email"] == "ana@example.test"
    assert con_dueno["estado"] == "activa"
    assert sin_dueno["user_id"] is None
    assert sin_dueno["expires_at"] is None
    for item in cuerpo["items"]:
        assert not {"key_hash", "api_key", "token", "is_active"} & item.keys()


def test_revocar_audita_con_el_id_del_admin(client):
    app.dependency_overrides[require_any_auth] = _admin
    try:
        with (
            patch(
                "api.routes.admin_api_keys._repo.revoke_by_id",
                return_value={"id": 3, "name": "legacy", "user_id": None},
            ) as revocar,
            patch("api.routes.admin_api_keys.log_event") as auditar,
        ):
            resp = client.delete("/api/v1/admin/api-keys/3")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json() == {"id": 3, "name": "legacy", "user_id": None, "estado": "revocada"}
    revocar.assert_called_once_with(3)
    kwargs = auditar.call_args.kwargs
    assert kwargs["event_type"] == "api_key.revoked"
    assert kwargs["user_id"] == 1
    assert kwargs["resource"] == "api_key:3"
    assert kwargs["detail"]["origen"] == "administracion"


def test_revocar_inexistente_es_404_y_no_audita(client):
    app.dependency_overrides[require_any_auth] = _admin
    try:
        with (
            patch("api.routes.admin_api_keys._repo.revoke_by_id", return_value=None),
            patch("api.routes.admin_api_keys.log_event") as auditar,
        ):
            resp = client.delete("/api/v1/admin/api-keys/999")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404
    auditar.assert_not_called()


def test_revocar_exige_admin(client):
    app.dependency_overrides[require_any_auth] = _no_admin
    try:
        with patch("api.routes.admin_api_keys._repo.revoke_by_id") as revocar:
            resp = client.delete("/api/v1/admin/api-keys/3")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 403
    revocar.assert_not_called()
