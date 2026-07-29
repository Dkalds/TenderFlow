"""Tests para observability/sentry.py — configuración y strip de PII."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch


class TestSentry:
    def setup_method(self):
        import observability.sentry as mod

        mod._configured = False
        self._mod = mod

    def test_configure_no_dsn(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SENTRY_DSN", None)
            result = self._mod.configure_sentry()
        assert result is False
        assert self._mod._configured is True

    def test_configure_already_configured(self):
        self._mod._configured = True
        assert self._mod.configure_sentry() is True

    def test_configure_import_error(self):
        with patch.dict(os.environ, {"SENTRY_DSN": "https://x@sentry.io/1"}):
            import builtins

            real_import = builtins.__import__

            def fake_import(name, *args, **kwargs):
                if "sentry_sdk" in name:
                    raise ImportError("no sentry")
                return real_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=fake_import):
                result = self._mod.configure_sentry()
        assert result is False

    def test_configure_success(self):
        mock_sdk = MagicMock()
        mock_logging_int = MagicMock()
        self._mod._configured = False

        with patch.dict(
            os.environ,
            {"SENTRY_DSN": "https://x@sentry.io/1", "ENVIRONMENT": "prod", "APP_VERSION": "1.0"},
        ):
            import builtins

            real_import = builtins.__import__

            def fake_import(name, *args, **kwargs):
                if name == "sentry_sdk":
                    return mock_sdk
                if "sentry_sdk.integrations.logging" in name:
                    m = MagicMock()
                    m.LoggingIntegration = mock_logging_int
                    return m
                return real_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=fake_import):
                result = self._mod.configure_sentry(service="test-svc")
        assert result is True
        mock_sdk.init.assert_called_once()
        mock_sdk.set_tag.assert_called_once_with("service", "test-svc")

    def test_strip_pii(self):
        event = {
            "request": {"headers": {"Authorization": "Bearer xxx", "Content-Type": "text/html"}},
            "user": {"id": "abc", "email": "test@test.com", "ip_address": "1.2.3.4"},
        }
        result = self._mod._strip_pii(event, {})
        assert result["request"]["headers"]["Authorization"] == "***REDACTED***"
        assert result["request"]["headers"]["Content-Type"] == "text/html"
        assert "email" not in result.get("user", {})
        assert "ip_address" not in result.get("user", {})
        assert result["user"]["id"] == "abc"

    def test_strip_pii_no_user(self):
        event = {"request": {"headers": {}}}
        result = self._mod._strip_pii(event, {})
        assert "user" not in result

    def test_strip_pii_empty_user_after_strip(self):
        event = {"user": {"email": "a@b.com", "ip_address": "1.1.1.1"}}
        result = self._mod._strip_pii(event, {})
        # user dict is empty after popping both fields, but code checks `if user:`
        # empty dict is falsy so event["user"] is NOT set back
        # But the original dict was mutated in-place via pop, so event["user"] is still {}
        assert result["user"] == {}

    def test_set_user_context_no_sdk(self):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if "sentry_sdk" in name:
                raise ImportError
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            self._mod.set_user_context("hash123")  # should not raise

    def test_set_user_context_with_sdk(self):
        mock_sdk = MagicMock()
        with patch.dict("sys.modules", {"sentry_sdk": mock_sdk}):
            self._mod.set_user_context("hash123", locale="en")
        mock_sdk.set_user.assert_called_once_with({"id": "hash123", "locale": "en"})

    def test_set_user_context_no_locale(self):
        mock_sdk = MagicMock()
        with patch.dict("sys.modules", {"sentry_sdk": mock_sdk}):
            self._mod.set_user_context("hash456")
        mock_sdk.set_user.assert_called_once_with({"id": "hash456"})
