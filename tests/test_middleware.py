"""Unit tests for api.middleware."""

from __future__ import annotations

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

    def test_wildcard_takes_rightmost_xff_hop(self):
        """FORWARDED_ALLOW_IPS='*' (PaaS) → último hop de XFF, no el primero.

        El proxy de la plataforma appendea la IP real al final; los hops de la
        izquierda los escribe el cliente. Hasta 2026-08 este caso devolvía
        request.client.host, que uvicorn (honrando el mismo '*') ya había
        reescrito con el primer hop — spoofeable (RFC-051).
        """
        settings_mock = MagicMock()
        settings_mock.FORWARDED_ALLOW_IPS = "*"
        with patch.dict("sys.modules", {"config": MagicMock(settings=settings_mock)}):
            req = _fake_request(
                client_host="10.220.3.7",
                headers={"X-Forwarded-For": "6.6.6.6, 203.0.113.50"},
            )
            result = _trusted_client_ip(req)
            assert result == "203.0.113.50"

    def test_wildcard_without_xff_falls_back_to_direct(self):
        settings_mock = MagicMock()
        settings_mock.FORWARDED_ALLOW_IPS = "*"
        with patch.dict("sys.modules", {"config": MagicMock(settings=settings_mock)}):
            req = _fake_request(client_host="10.220.3.7")
            result = _trusted_client_ip(req)
            assert result == "10.220.3.7"


# ── _client_key ──────────────────────────────────────────────────────────────


class TestClientKey:
    def test_api_key_does_not_create_a_separate_rate_limit_bucket(self):
        settings_mock = MagicMock()
        settings_mock.FORWARDED_ALLOW_IPS = "127.0.0.1"
        with patch.dict("sys.modules", {"config": MagicMock(settings=settings_mock)}):
            req = _fake_request(headers={"X-API-Key": "my-secret-key"})
            key = _client_key(req)
            assert key == "ip:1.2.3.4"

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
    @patch("api.middleware._client_key", return_value="ip:1.2.3.4")
    def test_solicitudes_blocked_redirects_instead_of_json(self, _ck, mock_rl):
        """El formulario de la landing no puede acabar en `problem+json`.

        `api/routes/publico_solicitudes.py` está escrito para que ningún camino
        de error enseñe JSON a un navegador, pero el corte por cuota ocurre
        antes del router: sin este caso propio, cinco envíos desde una IP
        —una oficina tras NAT, un reintento— dejaban el RFC 7807 en pantalla.
        """
        from api.middleware import SOLICITUDES_PATH

        limiter = MagicMock()
        limiter.check.return_value = False
        mock_rl.return_value = limiter

        async def _handler(request):
            return JSONResponse({"ok": True})

        app = Starlette(routes=[Route(SOLICITUDES_PATH, _handler, methods=["POST"])])
        app.add_middleware(RateLimitMiddleware)
        resp = TestClient(app).post(SOLICITUDES_PATH, follow_redirects=False)

        assert resp.status_code == 303
        assert resp.headers["location"] == "/solicitud-recibida?estado=limite"
        assert "Retry-After" in resp.headers
        assert "json" not in resp.headers.get("content-type", "")

    @patch("api.middleware.get_rate_limiter")
    @patch("api.middleware._client_key", return_value="ip:1.2.3.4")
    def test_other_paths_still_get_problem_json(self, _ck, mock_rl):
        """La excepción es solo del formulario: el resto de la API no cambia."""
        limiter = MagicMock()
        limiter.check.return_value = False
        mock_rl.return_value = limiter

        resp = TestClient(_make_app(RateLimitMiddleware)).get("/test")

        assert resp.status_code == 429

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

    def test_authenticated_json_gets_an_etag_and_stays_private(self):
        """El tráfico autenticado es el único que hay: si se excluye, no hay ETag.

        Hasta 2026-08 cualquier petición con cookie o API key salía por un atajo
        que ponía `private, no-store` y devolvía la respuesta **sin** ETag. Como
        prácticamente todos los endpoints exigen autenticación, el middleware
        bufferizaba el cuerpo de cada GET JSON sin emitir un solo ETag.
        """
        app = _make_app(ETagMiddleware, json_body=True, status=200)
        client = TestClient(app)

        resp = client.get("/test", headers={"X-API-Key": "k"})

        assert "ETag" in resp.headers
        cache_control = resp.headers["Cache-Control"]
        assert "private" in cache_control, "no debe poder cachearlo un proxy compartido"
        assert "no-cache" in cache_control, "debe revalidar, que es lo que habilita el 304"

    def test_authenticated_request_revalidates_with_304(self):
        app = _make_app(ETagMiddleware, json_body=True, status=200)
        client = TestClient(app)
        auth = {"X-API-Key": "k"}

        etag = client.get("/test", headers=auth).headers["ETag"]
        resp = client.get("/test", headers={**auth, "If-None-Match": etag})

        assert resp.status_code == 304
        assert "private" in resp.headers["Cache-Control"]

    def test_authenticated_non_json_is_never_stored(self):
        """Lo que no lleva ETag (streams, descargas) conserva `no-store`.

        Sin revalidación posible, lo correcto es que no se guarde en ningún
        sitio; relajarlo a `no-cache` dejaría el cuerpo en el disco del cliente.
        """

        async def _handler(request: Request) -> Response:
            return Response("data: hola\n\n", media_type="text/event-stream")

        app = Starlette(routes=[Route("/stream", _handler)])
        app.add_middleware(ETagMiddleware)
        client = TestClient(app)

        resp = client.get("/stream", headers={"X-API-Key": "k"})

        assert "ETag" not in resp.headers
        assert resp.headers["Cache-Control"] == "private, no-store"

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
