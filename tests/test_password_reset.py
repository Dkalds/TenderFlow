"""Recuperación de contraseña: no enumeración, un solo uso y revocación."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from api.app import app

_REQUEST = "/api/v1/auth/password-reset/request"
_CONFIRM = "/api/v1/auth/password-reset/confirm"
_NEW_PASSWORD = "NuevaClave-2026-Segura"  # pragma: allowlist secret # gitleaks:allow


def test_request_response_does_not_enumerate_accounts():
    client = TestClient(app)
    with (
        patch("api.routes.auth._password_reset_rate_allowed", new=AsyncMock(return_value=True)),
        patch("services.password_reset.issue_password_reset", return_value=(False, None)),
    ):
        missing = client.post(_REQUEST, json={"email": "missing@example.com"})
    with (
        patch("api.routes.auth._password_reset_rate_allowed", new=AsyncMock(return_value=True)),
        patch("services.password_reset.issue_password_reset", return_value=(True, "x" * 43)),
        patch("services.password_reset.send_password_reset_email", return_value=True),
    ):
        existing = client.post(_REQUEST, json={"email": "existing@example.com"})

    assert missing.status_code == existing.status_code == 202, (missing.text, existing.text)
    assert missing.json() == existing.json()


def test_request_rate_limit_keeps_generic_response():
    client = TestClient(app)
    with (
        patch("api.routes.auth._password_reset_rate_allowed", new=AsyncMock(return_value=False)),
        patch("services.password_reset.issue_password_reset") as issue,
    ):
        response = client.post(_REQUEST, json={"email": "someone@example.com"})

    assert response.status_code == 202, response.text
    issue.assert_not_called()


def test_confirm_rejects_invalid_or_expired_token():
    client = TestClient(app)
    with (
        patch("api.routes.auth._password_reset_rate_allowed", new=AsyncMock(return_value=True)),
        patch("db.password_reset.consume_reset_token", return_value=None),
    ):
        response = client.post(
            _CONFIRM,
            json={"token": "x" * 43, "password": _NEW_PASSWORD},
        )

    assert response.status_code == 400
    assert "caducado" in response.json()["detail"]


def test_token_is_single_use_and_revokes_sessions(tmp_db):
    from db.database import connect
    from db.password_reset import consume_reset_token, create_reset_token_for_email
    from db.sessions import create_session, validate_session
    from db.users import create_user, get_user_by_email
    from services.password_reset import token_hash
    from shared.auth_core import hash_password, verify_password

    email = "reset@example.test"
    user_id = create_user(email=email, password_hash=hash_password("Anterior-2026-Segura"))
    session = create_session(user_id)
    raw_token = "token-reset-seguro-" + "x" * 32
    digest = token_hash(raw_token)

    assert create_reset_token_for_email(email, digest, "2999-01-01T00:00:00+00:00") is True
    assert consume_reset_token(digest, hash_password(_NEW_PASSWORD)) == user_id
    assert consume_reset_token(digest, hash_password("OtraClave-2026-Segura")) is None
    assert validate_session(session) is None

    user = get_user_by_email(email)
    assert user is not None
    assert verify_password(_NEW_PASSWORD, str(user["password_hash"])) is True
    with connect() as connection:
        stored = connection.execute(
            "SELECT token_hash FROM password_reset_tokens WHERE user_id = %s",
            (user_id,),
        ).fetchone()
    assert stored is not None
    assert stored[0] == digest
    assert raw_token not in str(stored[0])
