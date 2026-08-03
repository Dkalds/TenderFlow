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
    @patch("api.routes.me.log_event")
    def test_logout_all_with_user(self, mock_log, mock_revoke, client, auth):
        resp = client.post("/api/v1/auth/logout-all", headers=auth)
        assert resp.status_code == 200
        assert resp.json()["sessions_revoked"] == 3

    @patch("api.routes.me.revoke_all_sessions", return_value=0)
    @patch("api.routes.me.log_event")
    def test_logout_all_no_user(self, mock_log, mock_revoke, client, auth):
        """Sin sesiones vivas el endpoint responde 200 con el contador a cero."""
        resp = client.post("/api/v1/auth/logout-all", headers=auth)
        assert resp.status_code == 200
        assert resp.json()["sessions_revoked"] == 0

    @patch("api.routes.me._key_repo")
    def test_list_my_keys(self, mock_repo, client, auth):
        mock_repo.get_all_for_user.return_value = [{"id": 1, "prefix": "abc"}]
        resp = client.get("/api/v1/me/keys", headers=auth)
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    @patch("api.routes.me.create_api_key")
    def test_rotate_my_key_rejects_api_key(self, mock_create, client, auth):
        """Rotar exige step-up de sesión: una API key ya no puede acuñar otra.

        Antes bastaba con el scope ``api_keys:rotate``, así que una key filtrada
        se rotaba sola y revocar la original no mataba a la rotada. El camino
        feliz (sesión reciente + ``key_id`` propio) vive en
        ``tests/test_unit_security_review_identity.py``.
        """
        resp = client.post("/api/v1/me/keys/rotate?key_id=1", headers=auth)
        assert resp.status_code == 403
        mock_create.assert_not_called()
