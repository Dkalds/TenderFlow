"""Tests del endpoint ``POST /api/v1/auth/register`` (sign-up email + password)."""

from __future__ import annotations

# Cumple la política equilibrada: >=10 chars, mayúsculas + minúsculas + dígito,
# sin patrones débiles conocidos.
VALID_PASSWORD = "Registro2026OK"


def test_register_success_sets_session(client):
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": "nuevo@example.com",
            "password": VALID_PASSWORD,
            "display_name": "Nuevo Usuario",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["email"] == "nuevo@example.com"
    assert data["display_name"] == "Nuevo Usuario"
    assert data["is_admin"] is False
    assert data["user_id"] >= 1
    # Auto-login: la cookie de sesión queda seteada...
    assert "session" in resp.cookies
    # ...y /me responde con el usuario recién creado usando esa sesión.
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "nuevo@example.com"


def test_register_weak_password_rejected(client):
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": "debil@example.com", "password": "corta"},
    )
    assert resp.status_code == 400
    assert "contraseña" in resp.json()["detail"].lower()


def test_register_duplicate_email_conflict(client):
    payload = {"email": "dup@example.com", "password": VALID_PASSWORD}
    first = client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201
    second = client.post("/api/v1/auth/register", json=payload)
    assert second.status_code == 409


def test_register_then_login_with_same_credentials(client):
    creds = {"email": "login@example.com", "password": VALID_PASSWORD}
    reg = client.post("/api/v1/auth/register", json={**creds, "display_name": "L"})
    assert reg.status_code == 201
    # El login con las mismas credenciales valida que hash_password produce un
    # hash compatible con verify_password.
    login = client.post("/api/v1/auth/login", json=creds)
    assert login.status_code == 200
    assert login.json()["email"] == "login@example.com"
