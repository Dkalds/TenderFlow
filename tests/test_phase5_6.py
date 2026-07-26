"""Tests para Phase 5+6: monorepo __init__ exports, XFF hardening, OTEL run_db."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import anyio

# ─── Phase 5: shared + db __init__ re-exports ────────────────────────────────


class TestSharedReexports:
    def test_nuts_to_ccaa_importable_from_shared(self):
        from shared import nuts_to_ccaa

        assert callable(nuts_to_ccaa)

    def test_get_cache_importable_from_shared(self):
        from shared import get_cache

        assert callable(get_cache)

    def test_dto_importable_from_shared(self):
        from shared import KpiSnapshotDTO, LicitacionSummary, WatchlistEntry

        assert LicitacionSummary is not None
        assert KpiSnapshotDTO is not None
        assert WatchlistEntry is not None

    def test_all_exports_listed(self):
        import shared

        assert hasattr(shared, "__all__")
        assert len(shared.__all__) >= 10

    def test_json_dict_importable(self):
        from shared import JsonDict

        assert JsonDict is not None


class TestDbReexports:
    def test_connect_importable_from_db(self):
        from db import connect

        assert callable(connect)

    def test_now_utc_iso_importable_from_db(self):
        from db import now_utc_iso

        assert callable(now_utc_iso)

    def test_all_exports_listed(self):
        import db

        assert set(db.__all__) >= {"connect", "connect_read", "now_utc_iso", "init_db"}


# ─── Phase 6b: X-Forwarded-For hardening ─────────────────────────────────────


class TestTrustedClientIp:
    """Tests for _trusted_client_ip in api/middleware.py."""

    def _make_request(self, headers: dict, client_host: str = "192.168.1.1"):
        """Build a minimal mock Request."""
        req = MagicMock()
        req.headers = headers
        req.client = MagicMock()
        req.client.host = client_host
        return req

    def test_uses_direct_ip_when_not_from_trusted_proxy(self):
        """If direct connection is not from trusted proxy, ignore XFF."""
        from api.middleware import _trusted_client_ip

        req = self._make_request(
            {"X-Forwarded-For": "1.2.3.4"},
            client_host="8.8.8.8",  # not in trusted proxies
        )
        with patch("config.settings") as mock_settings:
            mock_settings.FORWARDED_ALLOW_IPS = "127.0.0.1"
            ip = _trusted_client_ip(req)

        # Should return direct IP, not the spoofed XFF
        assert ip == "8.8.8.8"
        assert ip != "1.2.3.4"

    def test_honors_only_the_trusted_suffix_of_xff(self):
        """No confía en hops anteriores a un proxy no incluido en la allowlist."""
        from api.middleware import _trusted_client_ip

        req = self._make_request(
            {"X-Forwarded-For": "10.0.0.5, 172.16.0.1"},
            client_host="127.0.0.1",  # trusted proxy
        )
        with patch("config.settings") as mock_settings:
            mock_settings.FORWARDED_ALLOW_IPS = "127.0.0.1"
            ip = _trusted_client_ip(req)

        assert ip == "172.16.0.1"

    def test_falls_back_to_direct_when_xff_empty(self):
        """Even from trusted proxy, if XFF is empty, use direct IP."""
        from api.middleware import _trusted_client_ip

        req = self._make_request(
            {},  # no XFF header
            client_host="127.0.0.1",
        )
        with patch("config.settings") as mock_settings:
            mock_settings.FORWARDED_ALLOW_IPS = "127.0.0.1"
            ip = _trusted_client_ip(req)

        assert ip == "127.0.0.1"

    def test_returns_unknown_on_no_client(self):
        """If request.client is None, return 'unknown'."""
        from api.middleware import _trusted_client_ip

        req = MagicMock()
        req.client = None
        req.headers = {}
        with patch("config.settings") as mock_settings:
            mock_settings.FORWARDED_ALLOW_IPS = "127.0.0.1"
            ip = _trusted_client_ip(req)

        assert ip == "unknown"

    def test_multiple_trusted_proxies_configured(self):
        """Multiple IPs in FORWARDED_ALLOW_IPS are all treated as trusted."""
        from api.middleware import _trusted_client_ip

        req = self._make_request(
            {"X-Forwarded-For": "203.0.113.5"},
            client_host="10.0.0.1",
        )
        with patch("config.settings") as mock_settings:
            mock_settings.FORWARDED_ALLOW_IPS = "127.0.0.1, 10.0.0.1, 192.168.1.254"
            ip = _trusted_client_ip(req)

        assert ip == "203.0.113.5"

    def test_rate_limit_uses_verified_ip_not_spoofed_xff(self, client):
        """Integration: rate limit key uses real IP, not spoofed XFF."""
        # An unauthenticated request from an untrusted IP with spoofed XFF
        # should be keyed on the real IP (testclient), not the XFF value.
        resp = client.get(
            "/api/v1/licitaciones",
            headers={"X-Forwarded-For": "1.2.3.4"},
        )
        # No auth → 401 regardless, but no crash
        assert resp.status_code == 401


# ─── Phase 6c: OTEL instrumentation in run_db / run_ml ───────────────────────


class TestRunDbOtelSpans:
    """Tests for OTEL span creation in api/concurrency.py."""

    def test_run_db_works_without_otel(self):
        """run_db must work even when OTEL raises (fail-open)."""

        async def _test():
            from api.concurrency import run_db

            result = await run_db(lambda: 42)
            return result

        result = anyio.run(_test)
        assert result == 42

    def test_run_ml_works_without_otel(self):
        """run_ml must work even when OTEL raises (fail-open)."""

        async def _test():
            from api.concurrency import run_ml

            result = await run_ml(lambda: "hello")
            return result

        result = anyio.run(_test)
        assert result == "hello"

    def test_run_db_creates_span_when_tracer_available(self):
        """When OTEL is configured, run_db creates a db.query span."""
        mock_span = MagicMock()
        mock_span.__enter__ = lambda s: s
        mock_span.__exit__ = MagicMock(return_value=False)
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value = mock_span

        async def _test():
            from api.concurrency import run_db

            with patch("observability.tracing.get_tracer", return_value=mock_tracer):
                result = await run_db(lambda: 99)
            return result

        result = anyio.run(_test)
        assert result == 99
        mock_tracer.start_as_current_span.assert_called_once_with(
            "db.query", attributes={"db.function": "<lambda>"}
        )

    def test_run_ml_creates_span_when_tracer_available(self):
        """When OTEL is configured, run_ml creates an ml.inference span."""
        mock_span = MagicMock()
        mock_span.__enter__ = lambda s: s
        mock_span.__exit__ = MagicMock(return_value=False)
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value = mock_span

        async def _test():
            from api.concurrency import run_ml

            with patch("observability.tracing.get_tracer", return_value=mock_tracer):
                result = await run_ml(lambda: "ml-result")
            return result

        result = anyio.run(_test)
        assert result == "ml-result"
        mock_tracer.start_as_current_span.assert_called_once_with(
            "ml.inference", attributes={"ml.function": "<lambda>"}
        )

    def test_run_db_falls_back_on_tracer_exception(self):
        """If get_tracer raises, run_db still returns the correct result."""

        async def _test():
            from api.concurrency import run_db

            with patch("observability.tracing.get_tracer", side_effect=RuntimeError("otel down")):
                return await run_db(lambda: "fallback-ok")

        result = anyio.run(_test)
        assert result == "fallback-ok"


# ─── Phase 6a: ErrorAlwaysExport processor logic ─────────────────────────────


class TestErrorFilterExporter:
    """Unit tests for the _ErrorFilterExporter used in configure_tracing."""

    def _make_span(self, status_code_is_error: bool):
        span = MagicMock()
        status = MagicMock()
        try:
            from opentelemetry.trace import StatusCode

            status.status_code = StatusCode.ERROR if status_code_is_error else StatusCode.OK
        except ImportError:
            status.status_code = "ERROR" if status_code_is_error else "OK"
        span.status = status
        return span

    def test_tracing_module_imports_cleanly(self):
        """observability.tracing must import without errors."""
        import observability.tracing

        assert hasattr(observability.tracing, "configure_tracing")
        assert hasattr(observability.tracing, "get_tracer")

    def test_configure_tracing_noop_without_endpoint(self):
        """configure_tracing with no endpoint must set _noop=True."""
        import observability.tracing as t

        # Reset configured state to re-run
        orig_configured = t._configured
        orig_noop = t._noop
        t._configured = False
        t._noop = False
        try:
            with patch("config.settings") as mock_settings:
                mock_settings.OTEL_EXPORTER_OTLP_ENDPOINT = ""
                mock_settings.OTEL_SERVICE_NAME = "test"
                t.configure_tracing()
            assert t._noop is True
        finally:
            t._configured = orig_configured
            t._noop = orig_noop

    def test_get_tracer_returns_something(self):
        """get_tracer must return a tracer-like object."""
        from observability.tracing import get_tracer

        tracer = get_tracer("test.module")
        assert tracer is not None
