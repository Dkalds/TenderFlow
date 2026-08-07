"""Tests para api/routes/admin_users.py — gestión de usuarios admin."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from api.app import app
from api.routes.dual_auth import require_any_auth


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    return TestClient(app)


def _admin_user():
    return {"user_id": 1, "email": "admin@test.com", "is_admin": True, "auth_method": "session"}


def _non_admin_user():
    return {"user_id": 2, "email": "user@test.com", "is_admin": False, "auth_method": "session"}


class TestAdminListUsers:
    def test_requires_admin(self, client):
        app.dependency_overrides[require_any_auth] = lambda: _non_admin_user()
        try:
            resp = client.get("/api/v1/admin/users")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 403

    def test_lists_users(self, client):
        users_data = [
            {
                "id": 1,
                "email": "a@b.com",
                "display_name": "A",
                "is_admin": 1,
                "created_at": "2026-01-01",
                "deactivated_at": None,
                "last_access": None,
                "oauth_provider": "google",
            },
        ]
        app.dependency_overrides[require_any_auth] = lambda: _admin_user()
        try:
            with patch("api.routes.admin_users.list_users", return_value=users_data):
                resp = client.get("/api/v1/admin/users")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()[0]["email"] == "a@b.com"


class TestAdminDeactivateUser:
    def test_deactivate(self, client):
        target = {"id": 5, "email": "t@x.com", "is_admin": 0}
        app.dependency_overrides[require_any_auth] = lambda: _admin_user()
        try:
            with (
                patch("api.routes.admin_users.get_user_by_id", return_value=target),
                patch("api.routes.admin_users.deactivate_user") as mock_deact,
                patch(
                    "api.routes.admin_users.revoke_all_sessions", return_value=2
                ) as mock_sessions,
                patch(
                    "api.routes.admin_users.revoke_all_api_keys_for_user", return_value=1
                ) as mock_keys,
                patch("api.routes.admin_users.log_event"),
            ):
                resp = client.post(
                    "/api/v1/admin/users/5/deactivate", json={"action": "deactivate"}
                )
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["action"] == "deactivate"
        mock_deact.assert_called_once_with(5)
        # Dar de baja sin revocar credenciales dejaba las API keys del usuario
        # funcionando: `require_api_key` no miraba `deactivated_at`.
        mock_sessions.assert_called_once_with(5)
        mock_keys.assert_called_once_with(5)

    def test_cannot_deactivate_self(self, client):
        app.dependency_overrides[require_any_auth] = lambda: _admin_user()
        try:
            with patch("api.routes.admin_users.get_user_by_id", return_value={"id": 1}):
                resp = client.post(
                    "/api/v1/admin/users/1/deactivate", json={"action": "deactivate"}
                )
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 400

    def test_anonymize(self, client):
        target = {"id": 7, "email": "anon@x.com", "is_admin": 0}
        app.dependency_overrides[require_any_auth] = lambda: _admin_user()
        try:
            with (
                patch("api.routes.admin_users.get_user_by_id", return_value=target),
                patch("api.routes.admin_users.anonymize_user") as mock_anon,
                patch(
                    "api.routes.admin_users.revoke_all_sessions", return_value=0
                ) as mock_sessions,
                patch(
                    "api.routes.admin_users.revoke_all_api_keys_for_user", return_value=0
                ) as mock_keys,
                patch("api.routes.admin_users.log_event"),
            ):
                resp = client.post("/api/v1/admin/users/7/deactivate", json={"action": "anonymize"})
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        mock_anon.assert_called_once_with(7)
        mock_sessions.assert_called_once_with(7)
        mock_keys.assert_called_once_with(7)

    def test_reactivate_no_revoca_credenciales(self, client):
        """Reactivar es lo contrario de dar de baja: no debe revocar nada."""
        target = {"id": 9, "email": "back@x.com", "is_admin": 0}
        app.dependency_overrides[require_any_auth] = lambda: _admin_user()
        try:
            with (
                patch("api.routes.admin_users.get_user_by_id", return_value=target),
                patch("api.routes.admin_users.reactivate_user") as mock_react,
                patch("api.routes.admin_users.revoke_all_sessions") as mock_sessions,
                patch("api.routes.admin_users.revoke_all_api_keys_for_user") as mock_keys,
                patch("api.routes.admin_users.log_event"),
            ):
                resp = client.post(
                    "/api/v1/admin/users/9/deactivate", json={"action": "reactivate"}
                )
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        mock_react.assert_called_once_with(9)
        mock_sessions.assert_not_called()
        mock_keys.assert_not_called()


class TestAdminSetAdmin:
    def test_promote_user(self, client):
        target = {"id": 3, "email": "user@x.com", "is_admin": 0}
        app.dependency_overrides[require_any_auth] = lambda: _admin_user()
        try:
            with (
                patch("api.routes.admin_users.get_user_by_id", return_value=target),
                patch("api.routes.admin_users.set_admin") as mock_set,
                patch("api.routes.admin_users.log_event"),
            ):
                resp = client.put("/api/v1/admin/users/3/admin", json={"is_admin": True})
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        mock_set.assert_called_once_with(3, True, granted_by="panel")

    def test_cannot_change_own_admin(self, client):
        app.dependency_overrides[require_any_auth] = lambda: _admin_user()
        try:
            resp = client.put("/api/v1/admin/users/1/admin", json={"is_admin": False})
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 400
