"""Tests para services/rate_limit_redis.py — backend Redis + dispatcher."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch


class TestRateLimitRedis:
    def setup_method(self):
        import services.rate_limit_redis as mod

        self._mod = mod
        mod._client = None

    def test_has_redis_no_url(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REDIS_URL", None)
            # Even if redis module available, no URL means False
            assert not self._mod.has_redis()

    @patch.object(
        __import__("services.rate_limit_redis", fromlist=["_REDIS_AVAILABLE"]),
        "_REDIS_AVAILABLE",
        True,
    )
    def test_has_redis_with_url(self):
        with patch.dict(os.environ, {"REDIS_URL": "redis://localhost"}):
            assert self._mod.has_redis()

    def test_get_client_no_redis(self):
        with patch.object(self._mod, "has_redis", return_value=False):
            assert self._mod._get_client() is None

    def test_get_client_success(self):
        mock_redis_mod = MagicMock()
        mock_client = MagicMock()
        mock_redis_mod.Redis.from_url.return_value = mock_client
        self._mod._client = None

        with patch.object(self._mod, "has_redis", return_value=True):
            with patch.object(self._mod, "redis", mock_redis_mod):
                with patch.dict(os.environ, {"REDIS_URL": "redis://localhost"}):
                    result = self._mod._get_client()
        assert result is mock_client
        mock_client.ping.assert_called_once()

    def test_get_client_connection_error(self):
        mock_redis_mod = MagicMock()
        mock_redis_mod.Redis.from_url.side_effect = Exception("conn refused")
        self._mod._client = None

        with patch.object(self._mod, "has_redis", return_value=True):
            with patch.object(self._mod, "redis", mock_redis_mod):
                with patch.dict(os.environ, {"REDIS_URL": "redis://localhost"}):
                    result = self._mod._get_client()
        assert result is None

    def test_get_client_cached(self):
        sentinel = MagicMock()
        self._mod._client = sentinel
        with patch.object(self._mod, "has_redis", return_value=True):
            result = self._mod._get_client()
        assert result is sentinel

    def test_check_rate_limit_redis_no_client(self):
        with patch.object(self._mod, "_get_client", return_value=None):
            result = self._mod.check_rate_limit_redis("key1")
        assert result is None

    def test_check_rate_limit_redis_allowed(self):
        mock_client = MagicMock()
        mock_pipe = MagicMock()
        mock_client.pipeline.return_value = mock_pipe
        mock_pipe.execute.return_value = [None, None, 5, None]

        with patch.object(self._mod, "_get_client", return_value=mock_client):
            result = self._mod.check_rate_limit_redis("key1", max_calls=10)
        assert result is True

    def test_check_rate_limit_redis_exceeded(self):
        mock_client = MagicMock()
        mock_pipe = MagicMock()
        mock_client.pipeline.return_value = mock_pipe
        mock_pipe.execute.return_value = [None, None, 200, None]

        with patch.object(self._mod, "_get_client", return_value=mock_client):
            result = self._mod.check_rate_limit_redis("key1", max_calls=120)
        assert result is False

    def test_check_rate_limit_redis_pipeline_error(self):
        mock_client = MagicMock()
        mock_pipe = MagicMock()
        mock_client.pipeline.return_value = mock_pipe
        mock_pipe.execute.side_effect = Exception("pipe error")

        with patch.object(self._mod, "_get_client", return_value=mock_client):
            result = self._mod.check_rate_limit_redis("key1")
        assert result is None

    def test_check_rate_limit_dispatcher_redis(self):
        with patch.dict(os.environ, {"RATE_LIMIT_BACKEND": "redis"}):
            with patch.object(self._mod, "check_rate_limit_redis", return_value=True):
                result = self._mod.check_rate_limit("k")
        assert result is True

    def test_check_rate_limit_dispatcher_redis_fallback(self):
        with patch.dict(os.environ, {"RATE_LIMIT_BACKEND": "redis"}):
            with patch.object(self._mod, "check_rate_limit_redis", return_value=None):
                with patch("db.rate_limits.check_rate_limit_db", return_value=True) as mock_db:
                    result = self._mod.check_rate_limit("k")
        assert result is True
        mock_db.assert_called_once()

    def test_check_rate_limit_dispatcher_sqlite(self):
        with patch.dict(os.environ, {"RATE_LIMIT_BACKEND": "sqlite"}):
            with patch("db.rate_limits.check_rate_limit_db", return_value=False) as mock_db:
                result = self._mod.check_rate_limit("k", max_calls=50, window_seconds=30.0)
        assert result is False
        mock_db.assert_called_once_with("k", max_calls=50, window_seconds=30.0)

    def test_check_rate_limit_dispatcher_default_sqlite(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RATE_LIMIT_BACKEND", None)
            with patch("db.rate_limits.check_rate_limit_db", return_value=True):
                result = self._mod.check_rate_limit("k")
        assert result is True
