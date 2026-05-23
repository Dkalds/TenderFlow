"""Tests para db/webhooks.py – gestión de webhooks salientes."""

from __future__ import annotations

import hashlib
import hmac
from unittest.mock import MagicMock, patch

from db import webhooks as wh_mod

# ── helpers ──────────────────────────────────────────────────────────────────


def _create_sample(db_mod) -> tuple[int, str]:
    """Shortcut: crea un webhook de prueba y devuelve (id, secret)."""
    return wh_mod.create_webhook(
        name="test-hook",
        url="https://example.com/hook",
        event_types=["watchlist_match"],
    )


# ── tests ────────────────────────────────────────────────────────────────────


class TestSign:
    def test_hmac_sha256_correct(self):
        secret = "my-secret"  # pragma: allowlist secret
        payload = b'{"event":"test"}'
        expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        assert wh_mod._sign(secret, payload) == expected

    def test_different_secrets_produce_different_sigs(self):
        payload = b"same-payload"
        sig_a = wh_mod._sign("secret-a", payload)
        sig_b = wh_mod._sign("secret-b", payload)
        assert sig_a != sig_b


class TestCreateWebhook:
    def test_returns_id_and_secret(self, tmp_db):
        db_mod, _ = tmp_db
        wid, secret = _create_sample(db_mod)
        assert isinstance(wid, int) and wid > 0
        assert isinstance(secret, str) and len(secret) > 16


class TestListWebhooks:
    def test_excludes_secret(self, tmp_db):
        db_mod, _ = tmp_db
        _create_sample(db_mod)
        rows = wh_mod.list_webhooks()
        assert len(rows) >= 1
        for row in rows:
            assert "secret" not in row

    def test_returns_expected_fields(self, tmp_db):
        db_mod, _ = tmp_db
        _create_sample(db_mod)
        row = wh_mod.list_webhooks()[0]
        for col in ("id", "name", "url", "event_types", "active"):
            assert col in row


class TestDeleteWebhook:
    def test_delete_existing(self, tmp_db):
        db_mod, _ = tmp_db
        wid, _ = _create_sample(db_mod)
        assert wh_mod.delete_webhook(wid) is True

    def test_delete_nonexistent(self, tmp_db):
        _db_mod, _ = tmp_db
        assert wh_mod.delete_webhook(999999) is False


class TestTriggerEvent:
    @patch("db.webhooks.requests.post")
    def test_successful_delivery(self, mock_post, tmp_db):
        db_mod, _ = tmp_db
        _create_sample(db_mod)
        mock_resp = MagicMock(status_code=200)
        mock_post.return_value = mock_resp

        count = wh_mod.trigger_event("watchlist_match", {"id": 1})
        assert count == 1
        mock_post.assert_called_once()

        # Verify signature header was sent
        call_kwargs = mock_post.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        assert "X-Webhook-Signature" in headers

    @patch("db.webhooks.requests.post")
    def test_filters_by_event_type(self, mock_post, tmp_db):
        db_mod, _ = tmp_db
        # Webhook subscribed to watchlist_match only
        _create_sample(db_mod)
        mock_post.return_value = MagicMock(status_code=200)

        # Fire a different event
        count = wh_mod.trigger_event("daily_summary", {"msg": "hi"})
        assert count == 0
        mock_post.assert_not_called()

    @patch("db.webhooks.requests.post")
    def test_wildcard_event_type(self, mock_post, tmp_db):
        _db_mod, _ = tmp_db
        wh_mod.create_webhook(name="catch-all", url="https://example.com/all", event_types=["*"])
        mock_post.return_value = MagicMock(status_code=200)
        count = wh_mod.trigger_event("any_event", {})
        assert count == 1


class TestRecordDelivery:
    def test_resets_failure_count_on_success(self, tmp_db):
        db_mod, _ = tmp_db
        wid, _ = _create_sample(db_mod)

        # Simulate some failures first
        for _ in range(3):
            wh_mod._record_delivery(wid, 500, False)

        # Verify failure_count > 0
        rows = wh_mod.list_webhooks()
        hook = next(r for r in rows if r["id"] == wid)
        assert hook["failure_count"] == 3

        # Success resets counter
        wh_mod._record_delivery(wid, 200, True)
        rows = wh_mod.list_webhooks()
        hook = next(r for r in rows if r["id"] == wid)
        assert hook["failure_count"] == 0

    def test_disables_after_max_failures(self, tmp_db):
        db_mod, _ = tmp_db
        wid, _ = _create_sample(db_mod)

        for _ in range(wh_mod._MAX_FAILURES_BEFORE_DISABLE):
            wh_mod._record_delivery(wid, 500, False)

        rows = wh_mod.list_webhooks()
        hook = next(r for r in rows if r["id"] == wid)
        assert hook["active"] == 0
        assert hook["failure_count"] >= wh_mod._MAX_FAILURES_BEFORE_DISABLE
