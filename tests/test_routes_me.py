"""Tests para api/routes/me.py — export de datos GDPR, borrado, keys y logout-all."""

from __future__ import annotations

from unittest.mock import patch


class TestMeEndpoints:
    """Cover me.py uncovered lines."""

    @patch("api.routes.me.export_audit_log", return_value=[])
    @patch("api.routes.me.export_feedback", return_value=[])
    @patch("api.routes.me.export_watchlist", return_value=[])
    @patch("api.routes.me._key_repo")
    @patch("api.routes.me.log_event")
    def test_export_my_data(
        self,
        mock_log_event,
        mock_repo,
        mock_watchlist,
        mock_feedback,
        mock_audit,
        client,
        auth,
    ):
        mock_repo.get_all_for_user.return_value = []
        resp = client.get("/api/v1/me/data", headers=auth)
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"

    @patch("api.routes.me.anonymize_user_data")
    @patch("api.routes.me.log_event")
    def test_delete_my_data_rejects_api_key(self, mock_log_event, mock_anon, client, auth):
        resp = client.delete("/api/v1/me", headers=auth)
        assert resp.status_code == 403
        mock_anon.assert_not_called()

    @patch("api.routes.me.revoke_all_sessions", return_value=3)
    @patch("api.routes.me._get_user_id_from_key_id", return_value=42)
    @patch("api.routes.me.log_event")
    def test_logout_all_with_user(self, mock_log, mock_uid, mock_revoke, client, auth):
        resp = client.post("/api/v1/auth/logout-all", headers=auth)
        assert resp.status_code == 200
        assert resp.json()["sessions_revoked"] == 3

    @patch("api.routes.me._get_user_id_from_key_id", return_value=None)
    @patch("api.routes.me.log_event")
    def test_logout_all_no_user(self, mock_log, mock_uid, client, auth):
        resp = client.post("/api/v1/auth/logout-all", headers=auth)
        assert resp.status_code == 200
        assert resp.json()["sessions_revoked"] == 0

    @patch("api.routes.me._key_repo")
    def test_list_my_keys(self, mock_repo, client, auth):
        mock_repo.get_all_for_user.return_value = [{"id": 1, "prefix": "abc"}]
        resp = client.get("/api/v1/me/keys", headers=auth)
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    @patch("api.routes.me.log_event")
    @patch("api.routes.me.create_api_key", return_value="lic_newtoken123")
    @patch("api.routes.me._get_user_id_from_key_id", return_value=1)
    @patch("api.routes.me.set_key_expiry")
    @patch("api.routes.me.get_key_name_and_scopes", return_value=("test-key", ["read"]))
    def test_rotate_my_key(
        self, mock_info, mock_expiry, mock_uid, mock_create, mock_log, client, auth
    ):
        resp = client.post("/api/v1/me/keys/rotate", headers=auth)
        assert resp.status_code == 201
        data = resp.json()
        assert "new_token" in data
        assert data["new_token"] == "lic_newtoken123"

    @patch("api.routes.me.get_key_name_and_scopes", return_value=None)
    def test_rotate_my_key_not_found(self, mock_info, client, auth):
        resp = client.post("/api/v1/me/keys/rotate", headers=auth)
        assert resp.status_code == 404
