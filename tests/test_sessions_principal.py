"""Tests de ``db.sessions.validate_session_principal``.

Consolida en una consulta lo que antes eran 3-5 aperturas de conexión en serie
(``validate_session`` + ``get_user_by_id`` + ``is_totp_required``, más el
UPDATE de ``last_seen_at`` en su propia transacción). Estos tests fijan la
paridad de comportamiento con esa composición.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from db.database import connect


@pytest.fixture(autouse=True)
def _tmp_db(tmp_db):
    """Schema Postgres aislado por test."""


def _make_user(email: str = "user@example.com", *, is_admin: bool = False) -> int:
    from db.users import create_user

    user_id = create_user(
        email=email, password_hash="hash-irrelevante", display_name="Nombre Visible"
    )
    if is_admin:
        with connect() as c:
            c.execute("UPDATE users SET is_admin = 1 WHERE id = %s", (user_id,))
    return user_id


def test_returns_session_user_and_mfa_state() -> None:
    from db.sessions import create_session, validate_session_principal

    user_id = _make_user()
    token = create_session(user_id, ip="10.0.0.1")

    principal = validate_session_principal(token)

    assert principal is not None
    assert principal["user_id"] == user_id
    assert principal["id"] == user_id
    assert principal["email"] == "user@example.com"
    assert principal["display_name"] == "Nombre Visible"
    assert principal["is_admin"] is False
    assert principal["mfa_required"] is False
    assert principal["ip"] == "10.0.0.1"
    assert principal["authenticated_at"]


def test_reports_admin_flag() -> None:
    from db.sessions import create_session, validate_session_principal

    user_id = _make_user("admin@example.com", is_admin=True)
    token = create_session(user_id)

    principal = validate_session_principal(token)
    assert principal is not None
    assert principal["is_admin"] is True


def test_unknown_token_returns_none() -> None:
    from db.sessions import validate_session_principal

    assert validate_session_principal("token-que-no-existe") is None


def test_revoked_session_returns_none() -> None:
    from db.sessions import create_session, revoke_session, validate_session_principal

    token = create_session(_make_user())
    revoke_session(token)

    assert validate_session_principal(token) is None


def test_expired_session_returns_none() -> None:
    from db.sessions import _hash_token, create_session, validate_session_principal

    token = create_session(_make_user())
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    with connect() as c:
        c.execute(
            "UPDATE sessions SET expires_at = %s WHERE token_hash = %s",
            (past, _hash_token(token)),
        )

    assert validate_session_principal(token) is None


def test_idle_session_is_revoked_and_rejected() -> None:
    """Superado el umbral de inactividad, la sesión se revoca en la misma transacción."""
    from db.sessions import _hash_token, create_session, validate_session_principal

    token = create_session(_make_user())
    stale = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    with connect() as c:
        c.execute(
            "UPDATE sessions SET last_seen_at = %s WHERE token_hash = %s",
            (stale, _hash_token(token)),
        )

    assert validate_session_principal(token) is None

    with connect() as c:
        row = c.execute(
            "SELECT revoked FROM sessions WHERE token_hash = %s", (_hash_token(token),)
        ).fetchone()
    assert row[0], "la sesión inactiva debe quedar revocada"


def test_deactivated_user_invalidates_session() -> None:
    from db.sessions import create_session, validate_session_principal

    user_id = _make_user()
    token = create_session(user_id)
    with connect() as c:
        c.execute(
            "UPDATE users SET deactivated_at = %s WHERE id = %s",
            (datetime.now(UTC).isoformat(), user_id),
        )

    assert validate_session_principal(token) is None


def test_confirmed_totp_marks_mfa_required() -> None:
    """Lee `totp_secrets.confirmed` sin descifrar el secreto."""
    from db.sessions import create_session, validate_session_principal
    from db.totp import save_totp_secret

    user_id = _make_user()
    token = create_session(user_id)
    save_totp_secret(user_id, "SECRETO-BASE32", confirmed=True)

    principal = validate_session_principal(token)
    assert principal is not None
    assert principal["mfa_required"] is True


def test_unconfirmed_totp_does_not_require_mfa() -> None:
    from db.sessions import create_session, validate_session_principal
    from db.totp import save_totp_secret

    user_id = _make_user()
    token = create_session(user_id)
    save_totp_secret(user_id, "SECRETO-BASE32", confirmed=False)

    principal = validate_session_principal(token)
    assert principal is not None
    assert principal["mfa_required"] is False


def test_last_seen_refresh_is_throttled() -> None:
    """Una segunda validación inmediata no vuelve a escribir ``last_seen_at``."""
    from db.sessions import _hash_token, create_session, validate_session_principal

    token = create_session(_make_user())
    assert validate_session_principal(token) is not None

    with connect() as c:
        first = c.execute(
            "SELECT last_seen_at FROM sessions WHERE token_hash = %s", (_hash_token(token),)
        ).fetchone()[0]

    assert validate_session_principal(token) is not None

    with connect() as c:
        second = c.execute(
            "SELECT last_seen_at FROM sessions WHERE token_hash = %s", (_hash_token(token),)
        ).fetchone()[0]

    assert first == second, "last_seen_at se reescribió dentro de la ventana de throttle"
