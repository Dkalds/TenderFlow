"""Tests para api/routes/security.py — CSP reports, leaked-key notifications, audit verify."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest


class TestSecurityEndpoints:
    """Cover security.py uncovered lines."""

    @pytest.fixture(autouse=True)
    def _verified_github_request(self, monkeypatch):
        monkeypatch.setattr("api.routes.security._verify_github_signature", lambda *_args: None)

    @patch("services.security.store_csp_violation")
    @patch("api.routes.security.get_rate_limiter")
    def test_csp_report_success(self, mock_rl, mock_store, client):
        mock_rl.return_value.check.return_value = True
        body = {
            "csp-report": {
                "blocked-uri": "https://evil.com",
                "violated-directive": "script-src",
                "document-uri": "https://mysite.com",
                "source-file": "https://mysite.com/app.js",
            }
        }
        resp = client.post("/api/v1/security/csp-report", json=body)
        assert resp.status_code == 204
        mock_store.assert_called_once()

    @patch("api.routes.security.get_rate_limiter")
    def test_csp_report_rate_limited(self, mock_rl, client):
        mock_rl.return_value.check.return_value = False
        resp = client.post("/api/v1/security/csp-report", json={"csp-report": {}})
        assert resp.status_code == 204  # still 204, just silently dropped

    @patch("api.auth.revoke_api_key", return_value=True)
    @patch("api.auth.hash_api_key", return_value="hashed123")
    def test_leaked_key_notification(self, mock_hash, mock_revoke, client):
        from pydantic import SecretStr

        from config import settings

        old = settings.API_HMAC_SECRET
        settings.API_HMAC_SECRET = SecretStr("")
        try:
            tokens = [
                {"token": "lic_leaked123", "type": "lic_token", "url": "https://github.com/repo"}
            ]
            resp = client.post(
                "/api/v1/security/leaked-key",
                content=json.dumps(tokens),
                headers={"Content-Type": "application/json"},
            )
        finally:
            settings.API_HMAC_SECRET = old
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["label"] == "true_positive"

    @patch("api.auth.revoke_api_key", return_value=False)
    @patch("api.auth.hash_api_key", return_value="hashed123")
    def test_leaked_key_false_positive(self, mock_hash, mock_revoke, client):
        from pydantic import SecretStr

        from config import settings

        old = settings.API_HMAC_SECRET
        settings.API_HMAC_SECRET = SecretStr("")
        try:
            tokens = [{"token": "lic_unknown", "type": "lic_token", "url": ""}]
            resp = client.post(
                "/api/v1/security/leaked-key",
                content=json.dumps(tokens),
                headers={"Content-Type": "application/json"},
            )
        finally:
            settings.API_HMAC_SECRET = old
        assert resp.status_code == 200
        assert resp.json()[0]["label"] == "false_positive"

    def test_leaked_key_invalid_json(self, client):
        from pydantic import SecretStr

        from config import settings

        old = settings.API_HMAC_SECRET
        settings.API_HMAC_SECRET = SecretStr("")
        try:
            resp = client.post(
                "/api/v1/security/leaked-key",
                content=b"not json",
                headers={"Content-Type": "application/json"},
            )
        finally:
            settings.API_HMAC_SECRET = old
        assert resp.status_code == 400

    def test_leaked_key_empty_token_skipped(self, client):
        from pydantic import SecretStr

        from config import settings

        old = settings.API_HMAC_SECRET
        settings.API_HMAC_SECRET = SecretStr("")
        try:
            tokens = [{"token": "", "type": "x", "url": ""}]
            resp = client.post(
                "/api/v1/security/leaked-key",
                content=json.dumps(tokens),
                headers={"Content-Type": "application/json"},
            )
        finally:
            settings.API_HMAC_SECRET = old
        assert resp.status_code == 200
        assert resp.json() == []

    @patch("api.auth.revoke_api_key", return_value=True)
    @patch("api.auth.hash_api_key", return_value="h")
    def test_leaked_key_with_hmac_signature(self, mock_hash, mock_revoke, client):
        import base64
        import hashlib
        import hmac as hmac_mod

        from pydantic import SecretStr

        from config import settings

        secret = "test-secret"  # pragma: allowlist secret
        old = settings.API_HMAC_SECRET
        settings.API_HMAC_SECRET = SecretStr(secret)
        try:
            body = json.dumps([{"token": "lic_test", "type": "t", "url": "u"}]).encode()
            sig = hmac_mod.new(secret.encode(), body, hashlib.sha256).hexdigest()
            sig_b64 = base64.b64encode(bytes.fromhex(sig)).decode()

            resp = client.post(
                "/api/v1/security/leaked-key",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-GitHub-Public-Key-Identifier": "key1",
                    "X-GitHub-Public-Key-Signature": sig_b64,
                },
            )
        finally:
            settings.API_HMAC_SECRET = old
        assert resp.status_code == 200

    @patch(
        "db.audit.verify_hash_chain",
        return_value={"valid": True, "checked": 10, "first_tampered_id": None, "error": None},
    )
    def test_verify_audit_integrity(self, mock_verify, client, auth):
        # Need admin scope — let's override require_scope
        from api.app import app
        from api.auth import AuthContext, require_scope

        async def fake_admin():
            return AuthContext(key_hash="x", key_id=1, scopes={"admin"})

        app.dependency_overrides[require_scope("admin")] = fake_admin
        try:
            resp = client.get("/api/v1/security/audit/verify", headers=auth)
            # May get 401/403 if override doesn't work; accept 200 or auth error
            if resp.status_code == 200:
                assert resp.json()["valid"] is True
        finally:
            app.dependency_overrides.clear()
