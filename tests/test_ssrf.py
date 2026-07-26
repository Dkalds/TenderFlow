"""Tests de shared/ssrf.py — validación SSRF/DNS-rebinding compartida.

Extraído de api/routes/webhooks.py (RFC llm-dependencia-gestionada §C3.0) para
que db/webhooks.py::trigger_event use la misma validación que el ping manual.
Los tests de comportamiento contra dominios reales/privados ya viven en
test_ola3_security.py (vía api.routes.webhooks) y test_webhooks.py (vía
db.webhooks.trigger_event); este archivo cubre el módulo compartido directo.
"""

from __future__ import annotations

import pytest

from shared.ssrf import is_ssrf_url, validate_outbound_url


class TestIsSsrfUrl:
    def test_private_ip_literal_blocked(self):
        assert is_ssrf_url("http://127.0.0.1/hook") is True

    def test_no_hostname_blocked(self):
        assert is_ssrf_url("not-a-url") is True

    def test_rebinding_suffix_blocked_without_dns(self):
        # Bloqueado por sufijo antes de intentar resolver DNS.
        assert is_ssrf_url("http://10.0.0.1.nip.io/hook") is True

    def test_public_domain_allowed(self):
        assert is_ssrf_url("https://example.com/webhook") is False


class TestValidateOutboundUrl:
    def test_private_ip_raises(self):
        with pytest.raises(ValueError, match="no global"):
            validate_outbound_url("https://192.168.1.1/hook")

    def test_no_hostname_raises(self):
        with pytest.raises(ValueError):
            validate_outbound_url("not-a-url")

    def test_rebinding_domain_raises(self):
        with pytest.raises(ValueError, match="DNS rebinding"):
            validate_outbound_url("https://127.0.0.1.nip.io/hook")

    def test_public_domain_keeps_hostname_for_tls_sni(self):
        url = "https://example.com/hook?x=1"
        assert validate_outbound_url(url) == url
