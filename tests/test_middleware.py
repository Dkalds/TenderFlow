"""Unit tests for api.middleware."""

from __future__ import annotations

import hashlib
from unittest.mock import MagicMock, patch

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.testclient import TestClient

from api.middleware import (
    ETagMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    _client_key,
    _trusted_client_ip,
)

# ── helpers ──────────────────────────────────────────────────────────────────


def _make_app(
    middleware_cls, *, handler=None, json_body: bool = True, status: int = 200, **mw_kwargs
):
    """Build a tiny Starlette app wrapped with the given middleware."""

    async def _default_handler(request: Request) -> Response:
        if json_body:
            return JSONResponse({"ok": True}, status_code=status)
        return Response("plain", status_code=status, media_type="text/plain")

    handler = handler or _default_handler

    app = Starlette(
        routes=[
            Route("/test", handler, methods=["GET", "POST"]),
            Route("/api/v1/health", handler),
            Route("/api/docs", handler),
        ]
    )
    app.add_middleware(middleware_cls, **mw_kwargs)
    return app


def _fake_request(
    *,
    path: str = "/test",
    method: str = "GET",
    headers: dict | None = None,
    client_host: str = "1.2.3.4",
    scheme: str = "http",
) -> Request:
    """Build a minimal ASGI Request for unit-testing free functions."""
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "server": ("localhost", 80),
        "scheme": scheme,
    }
    if client_host:
        scope["client"] = (client_host, 12345)
    else:
        scope["client"] = None
    return Request(scope)


# ── SecurityHeadersMiddleware ────────────────────────────────────────────────


class TestSecurityHeadersMiddleware:
    def test_headers_are_set(self):
        app = _make_app(SecurityHeadersMiddleware)
        client = TestClient(app)
        resp = client.get("/test")
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert "Permissions-Policy" in resp.headers
        assert "Content-Security-Policy" in resp.headers

    def test_hsts_not_set_on_http(self):
        app = _make_app(SecurityHeadersMiddleware)
        client = TestClient(app)
        resp = client.get("/test")
        # TestClient uses http by default
        assert "Strict-Transport-Security" not in resp.headers

    def test_hsts_set_via_x_forwarded_proto(self):
        app = _make_app(SecurityHeadersMiddleware)
        client = TestClient(app)
        resp = client.get("/test", headers={"X-Forwarded-Proto": "https"})
        assert "Strict-Transport-Security" in resp.headers
        assert "max-age=" in resp.headers["Strict-Transport-Security"]


# ── _trusted_client_ip ───────────────────────────────────────────────────────


class TestTrustedClientIp:
    def test_direct_ip_returned(self):
        settings_mock = MagicMock()
        settings_mock.FORWARDED_ALLOW_IPS = "10.0.0.1"
        with patch.dict("sys.modules", {"config": MagicMock(settings=settings_mock)}):
            req = _fake_request(client_host="1.2.3.4")
            result = _trusted_client_ip(req)
            assert result == "1.2.3.4"

    def test_trusted_proxy_honors_xff(self):
        settings_mock = MagicMock()
        settings_mock.FORWARDED_ALLOW_IPS = "10.0.0.1"
        with patch.dict("sys.modules", {"config": MagicMock(settings=settings_mock)}):
            req = _fake_request(
                client_host="10.0.0.1",
                headers={"X-Forwarded-For": "203.0.113.50, 10.0.0.1"},
            )
            result = _trusted_client_ip(req)
            assert result == "203.0.113.50"

    def test_untrusted_proxy_ignores_xff(self):
        settings_mock = MagicMock()
        settings_mock.FORWARDED_ALLOW_IPS = "10.0.0.1"
        with patch.dict("sys.modules", {"config": MagicMock(settings=settings_mock)}):
            req = _fake_request(
                client_host="9.9.9.9",
                headers={"X-Forwarded-For": "203.0.113.50"},
            )
            result = _trusted_client_ip(req)
            assert result == "9.9.9.9"

    def test_error_returns_unknown(self):
        """When config import fails entirely, return 'unknown'."""
        with patch.dict("sys.modules", {"config": None}):
            req = _fake_request(client_host="1.2.3.4")
            result = _trusted_client_ip(req)
            assert result == "unknown"


# ── _client_key ──────────────────────────────────────────────────────────────


class TestClientKey:
    def test_api_key_is_hashed(self):
        settings_mock = MagicMock()
        settings_mock.FORWARDED_ALLOW_IPS = "127.0.0.1"
        with patch.dict("sys.modules", {"config": MagicMock(settings=settings_mock)}):
            req = _fake_request(headers={"X-API-Key": "my-secret-key"})
            key = _client_key(req)
            expected_hash = hashlib.sha256(b"my-secret-key").hexdigest()[:16]
            assert key == f"ak:{expected_hash}"

    def test_ip_fallback(self):
        settings_mock = MagicMock()
        settings_mock.FORWARDED_ALLOW_IPS = "127.0.0.1"
        with patch.dict("sys.modules", {"config": MagicMock(settings=settings_mock)}):
            req = _fake_request(client_host="5.6.7.8")
            key = _client_key(req)
            assert key == "ip:5.6.7.8"


# ── RateLimitMiddleware ──────────────────────────────────────────────────────


class TestRateLimitMiddleware:
    @patch("api.middleware.get_rate_limiter")
    @patch("api.middleware._client_key", return_value="ip:1.2.3.4")
    def test_allowed_request_passes(self, _ck, mock_rl):
        limiter = MagicMock()
        limiter.check.return_value = True
        mock_rl.return_value = limiter

        app = _make_app(RateLimitMiddleware)
        client = TestClient(app)
        resp = client.get("/test")
        assert resp.status_code == 200

    @patch("api.middleware.get_rate_limiter")
    @patch("api.middleware._client_key", return_value="ip:1.2.3.4")
    def test_blocked_returns_429(self, _ck, mock_rl):
        limiter = MagicMock()
        limiter.check.return_value = False
        mock_rl.return_value = limiter

        app = _make_app(RateLimitMiddleware)
        client = TestClient(app)
        resp = client.get("/test")
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers
        assert "X-RateLimit-Limit" in resp.headers

    @patch("api.middleware.get_rate_limiter")
    def test_excluded_path_bypasses(self, mock_rl):
        limiter = MagicMock()
        limiter.check.return_value = False  # would block if checked
        mock_rl.return_value = limiter

        app = _make_app(RateLimitMiddleware)
        client = TestClient(app)
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        limiter.check.assert_not_called()


    def test_ask_endpoint_in_heavy_limits(self):
        """Verify /api/v1/ask is rate-limited to 10 req/min (issue #58)."""
        from api.middleware import _HEAVY_ENDPOINT_LIMITS

        assert "/api/v1/ask" in _HEAVY_ENDPOINT_LIMITS
        assert _HEAVY_ENDPOINT_LIMITS["/api/v1/ask"] == 10

    def test_ask_models_endpoint_in_heavy_limits(self):
        """Verify /api/v1/ask/models is rate-limited to 30 req/min."""
        from api.middleware import _HEAVY_ENDPOINT_LIMITS

        assert "/api/v1/ask/models" in _HEAVY_ENDPOINT_LIMITS
        assert _HEAVY_ENDPOINT_LIMITS["/api/v1/ask/models"] == 30

    @patch("api.middleware.get_rate_limiter")
    @patch("api.middleware._client_key", return_value="ip:1.2.3.4")
    def test_ask_endpoint_uses_heavy_limit(self, _ck, mock_rl):
        """The middleware must pass max_calls=10 for /api/v1/ask."""
        limiter = MagicMock()
        limiter.check.return_value = True
        mock_rl.return_value = limiter

        async def _handler(request):
            return JSONResponse({"ok": True})

        app = Starlette(
            routes=[Route("/api/v1/ask", _handler, methods=["GET", "POST"])],
        )
        app.add_middleware(RateLimitMiddleware)
        client = TestClient(app)
        client.post("/api/v1/ask")
        limiter.check.assert_called_once()
        call_kwargs = limiter.check.call_args
        assert call_kwargs.kwargs.get("max_calls") == 10 or call_kwargs[1].get("max_calls") == 10

# ── ETagMiddleware ───────────────────────────────────────────────────────────


class TestETagMiddleware:
    def test_adds_etag_to_get_200_json(self):
        app = _make_app(ETagMiddleware, json_body=True, status=200)
        client = TestClient(app)
        resp = client.get("/test")
        assert resp.status_code == 200
        assert "ETag" in resp.headers
        assert resp.headers["ETag"].startswith('W/"')

    def test_returns_304_on_if_none_match(self):
        app = _make_app(ETagMiddleware, json_body=True, status=200)
        client = TestClient(app)
        # First request to get the ETag
        resp1 = client.get("/test")
        etag = resp1.headers["ETag"]
        # Second request with If-None-Match
        resp2 = client.get("/test", headers={"If-None-Match": etag})
        assert resp2.status_code == 304

    def test_skips_non_get(self):
        app = _make_app(ETagMiddleware, json_body=True, status=200)
        client = TestClient(app)
        resp = client.post("/test")
        assert "ETag" not in resp.headers

    def test_skips_non_200(self):
        async def _handler(request: Request) -> Response:
            return JSONResponse({"error": "not found"}, status_code=404)

        app = Starlette(routes=[Route("/test", _handler)])
        app.add_middleware(ETagMiddleware)
        client = TestClient(app)
        resp = client.get("/test")
        assert "ETag" not in resp.headers

    def test_skips_non_json(self):
        app = _make_app(ETagMiddleware, json_body=False, status=200)
        client = TestClient(app)
        resp = client.get("/test")
        assert "ETag" not in resp.headers
