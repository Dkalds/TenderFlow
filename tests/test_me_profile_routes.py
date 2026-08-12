"""Cobertura de GET/PUT/DELETE ``/api/v1/me/profile``.

Ningún test mencionaba estos endpoints pese a gobernar el perfil de scoring
personalizado del usuario. Se añaden aquí porque los tres se reescribieron en
esta rama para sacar su acceso a BD del event loop (``run_db``), y sin una
prueba end-to-end ese cambio no quedaba ejercitado.
"""

from __future__ import annotations

import pytest

_EMAIL = "perfil@example.com"
_PASSWORD = "Perfil-2026-Seguro"  # pragma: allowlist secret


@pytest.fixture()
def session_client(client, api_db):
    """TestClient con sesión activa y su token CSRF."""
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": _EMAIL, "password": _PASSWORD},
    )
    assert reg.status_code == 201, reg.text
    login = client.post(
        "/api/v1/auth/login",
        json={"email": _EMAIL, "password": _PASSWORD},
    )
    assert login.status_code == 200, login.text
    return client, login.cookies["csrf_token"]


def test_get_profile_sin_perfil_devuelve_objeto_vacio(session_client):
    """Un usuario recién creado no tiene perfil: el contrato es un objeto vacío."""
    client, _ = session_client

    resp = client.get("/api/v1/me/profile")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["weights"] is None
    assert body["visibility"] == "private"


def test_put_y_get_profile_persisten_los_pesos(session_client):
    client, csrf = session_client

    put = client.put(
        "/api/v1/me/profile",
        json={
            "weights": {"afinidad": 50, "importe": 30, "plazo": 20},
            "afinidad_keywords": ["sap", "s/4hana"],
            "importe_min": 50000,
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert put.status_code == 200, put.text

    got = client.get("/api/v1/me/profile")
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["weights"] == {"afinidad": 50, "importe": 30, "plazo": 20}
    assert body["afinidad_keywords"] == ["sap", "s/4hana"]
    assert body["importe_min"] == 50000


def test_put_profile_rechaza_pesos_que_no_suman_100(session_client):
    """La validación de pesos vive en el DTO, antes de tocar la BD."""
    client, csrf = session_client

    resp = client.put(
        "/api/v1/me/profile",
        json={"weights": {"afinidad": 10, "importe": 10, "plazo": 10}},
        headers={"X-CSRF-Token": csrf},
    )

    assert resp.status_code in (400, 422), resp.text


def test_delete_profile_vuelve_a_los_defaults(session_client):
    """Borrar el perfil devuelve el scoring a los settings globales."""
    client, csrf = session_client

    client.put(
        "/api/v1/me/profile",
        json={"weights": {"afinidad": 50, "importe": 30, "plazo": 20}},
        headers={"X-CSRF-Token": csrf},
    )

    delete = client.delete("/api/v1/me/profile", headers={"X-CSRF-Token": csrf})
    assert delete.status_code == 200, delete.text

    got = client.get("/api/v1/me/profile")
    assert got.status_code == 200
    assert got.json()["weights"] is None


def test_profile_exige_autenticacion(client, api_db):
    """Sin sesión no se llega al cuerpo del handler."""
    assert client.get("/api/v1/me/profile").status_code in (401, 403)
