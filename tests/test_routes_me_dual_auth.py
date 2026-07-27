"""Tests de /api/v1/me/data y /api/v1/me (DELETE) con autenticación dual
(F13·C3.1/C3.2, plan Pliegos+RAG).

Antes de este cambio ambos endpoints solo aceptaban API key
(``require_api_key``) e identificaban los datos de usuario por el
``key_hash`` crudo — lo que dejaba fuera a los usuarios de solo-sesión y,
además, nunca encontraba nada en watchlist/watchlist_items/watchlist_rules/
user_profiles/user_notifications porque esas tablas se escriben con
``sha256(email o key_hash)[:16]``, no con el hash crudo (ver services/gdpr.py).
Estos tests cubren el fix con sesión OAuth Y verifican que el comportamiento
existente con API key no cambió.
"""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from api.app import app
from api.routes.dual_auth import require_any_auth
from api.routes.me import _user_key
from api.routes.watchlist_rules import _user_key as _watchlist_rules_user_key

# Fixtures client, auth, api_db se heredan de conftest.py


def _session_ctx(user_id: int = 7, email: str = "session-user@test.com"):
    return {
        "user_id": user_id,
        "email": email,
        "display_name": "Session User",
        "is_admin": False,
        "auth_method": "session",
        "authenticated_at": datetime.now(UTC).isoformat(),
    }


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# user_key derivation consistency (regresión del bug de identidad)
# ---------------------------------------------------------------------------


def test_user_key_matches_watchlist_rules_convention():
    """me.py y watchlist_rules.py deben derivar el mismo user_key del mismo ctx."""
    ctx = _session_ctx()
    assert _user_key(ctx) == _watchlist_rules_user_key(ctx)


# ---------------------------------------------------------------------------
# GET /me/data — sesión OAuth
# ---------------------------------------------------------------------------


def test_export_my_data_session_auth_returns_zip(client, api_db):
    app.dependency_overrides[require_any_auth] = _session_ctx
    resp = client.get("/api/v1/me/data")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/zip"


def test_export_my_data_session_includes_watchlist_rule(client, api_db):
    """Regresión: una regla creada vía sesión debe aparecer en el export.

    Antes del fix, export_watchlist* se consultaba con el key_hash crudo
    (inexistente para sesión) y siempre devolvía listas vacías.
    """
    ctx = _session_ctx()
    user_key = _user_key(ctx)

    from services.watchlist_rules import WatchlistRule, create_rule

    create_rule(user_key, WatchlistRule(keyword="SAP", frequency="daily"))

    app.dependency_overrides[require_any_auth] = lambda: ctx
    resp = client.get("/api/v1/me/data")
    assert resp.status_code == 200, resp.text

    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    import json

    rules = json.loads(zf.read("watchlist_rules.json"))
    assert len(rules) == 1
    assert rules[0]["keyword"] == "SAP"


def test_export_my_data_session_uses_get_all_for_user_for_keys(client, api_db):
    """Con sesión (sin API key), las api_keys exportadas vienen de get_all_for_user."""
    ctx = _session_ctx(user_id=99)
    app.dependency_overrides[require_any_auth] = lambda: ctx
    with patch(
        "api.routes.me._key_repo.get_all_for_user", return_value=[{"name": "k"}]
    ) as mock_get:
        resp = client.get("/api/v1/me/data")
    assert resp.status_code == 200, resp.text
    mock_get.assert_called_once_with(99)


# ---------------------------------------------------------------------------
# DELETE /me — sesión OAuth vs API key
# ---------------------------------------------------------------------------


def test_delete_my_data_session_anonymizes_account_and_revokes_everything(client, api_db):
    ctx = _session_ctx(user_id=42)
    app.dependency_overrides[require_any_auth] = lambda: ctx
    with (
        patch("db.users.anonymize_user") as mock_anon_user,
        patch("api.routes.me.revoke_all_sessions", return_value=2) as mock_revoke_sessions,
        patch("api.routes.me.revoke_all_api_keys_for_user", return_value=1) as mock_revoke_keys,
    ):
        resp = client.request("DELETE", "/api/v1/me", json={"confirmation": "DELETE"})
    assert resp.status_code == 200, resp.text
    mock_anon_user.assert_called_once_with(42)
    mock_revoke_sessions.assert_called_once_with(42)
    mock_revoke_keys.assert_called_once_with(42)


def test_delete_my_data_rejects_api_key_even_with_explicit_confirmation(client, auth, api_db):
    """Una credencial de automatización no puede borrar una cuenta humana."""
    with (
        patch("db.users.anonymize_user") as mock_anon_user,
        patch("api.routes.me.revoke_all_sessions") as mock_revoke_sessions,
        patch("api.routes.me.revoke_all_api_keys_for_user") as mock_revoke_keys,
        patch("api.routes.me.anonymize_user_data") as mock_anon_data,
    ):
        resp = client.request("DELETE", "/api/v1/me", headers=auth, json={"confirmation": "DELETE"})
    assert resp.status_code == 403, resp.text
    mock_anon_user.assert_not_called()
    mock_revoke_sessions.assert_not_called()
    mock_revoke_keys.assert_not_called()
    mock_anon_data.assert_not_called()


def test_delete_my_data_session_deletes_watchlist_rule(client, api_db):
    """End-to-end: borrar mis datos por sesión borra mis reglas de watchlist."""
    ctx = _session_ctx(user_id=55)
    user_key = _user_key(ctx)

    from services.watchlist_rules import WatchlistRule, create_rule, list_rules

    create_rule(user_key, WatchlistRule(keyword="SAP", frequency="daily"))
    assert len(list_rules(user_key)) == 1

    app.dependency_overrides[require_any_auth] = lambda: ctx
    resp = client.request("DELETE", "/api/v1/me", json={"confirmation": "DELETE"})
    assert resp.status_code == 200, resp.text
    assert list_rules(user_key) == []


# ---------------------------------------------------------------------------
# POST /auth/logout-all — sesión OAuth
# ---------------------------------------------------------------------------


def test_logout_all_session_uses_own_user_id(client, api_db):
    ctx = _session_ctx(user_id=11)
    app.dependency_overrides[require_any_auth] = lambda: ctx
    with patch("api.routes.me.revoke_all_sessions", return_value=3) as mock_revoke:
        resp = client.post("/api/v1/auth/logout-all")
    assert resp.status_code == 200, resp.text
    assert resp.json()["sessions_revoked"] == 3
    mock_revoke.assert_called_once_with(11)
