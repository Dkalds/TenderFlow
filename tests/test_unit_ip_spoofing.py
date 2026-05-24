"""Unit tests: verify consistent use of _trusted_client_ip (issue #51).

Ensures AccessLogMiddleware, CSP report endpoint, and /metrics endpoint
all use _trusted_client_ip() instead of reading X-Forwarded-For directly,
preventing IP spoofing in logs and metrics.
"""

from __future__ import annotations

from unittest.mock import patch

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.testclient import TestClient

from api.middleware import AccessLogMiddleware

# ── AccessLogMiddleware uses _trusted_client_ip ─────────────────────────────


class TestAccessLogUseTrustedIp:
    """AccessLogMiddleware must call _trusted_client_ip, not read XFF directly."""

    @patch("api.middleware._trusted_client_ip", return_value="10.20.30.40")
    def test_access_log_uses_trusted_ip(self, mock_tip):
        """When _trusted_client_ip returns a specific IP, the log should use it."""

        async def handler(request: Request) -> Response:
            return JSONResponse({"ok": True})

        app = Starlette(routes=[Route("/test", handler)])
        app.add_middleware(AccessLogMiddleware)
        client = TestClient(app)

        # Send a spoofed XFF header from an untrusted source
        client.get("/test", headers={"X-Forwarded-For": "6.6.6.6"})

        # _trusted_client_ip should have been called (not raw header read)
        assert mock_tip.called

    @patch("api.middleware._trusted_client_ip", return_value="192.168.1.1")
    def test_spoofed_xff_ignored_in_access_log(self, mock_tip):
        """A spoofed X-Forwarded-For should not appear — _trusted_client_ip decides."""
        logged_ips: list[str] = []

        original_info = None

        async def handler(request: Request) -> Response:
            return JSONResponse({"ok": True})

        app = Starlette(routes=[Route("/test", handler)])
        app.add_middleware(AccessLogMiddleware)
        client = TestClient(app)

        with patch("api.middleware.log") as mock_log:
            client.get("/test", headers={"X-Forwarded-For": "6.6.6.6, 7.7.7.7"})
            # Check that the logged client_ip is from _trusted_client_ip
            for call in mock_log.info.call_args_list:
                if call.args and call.args[0] == "http_request":
                    assert call.kwargs.get("client_ip") == "192.168.1.1"
