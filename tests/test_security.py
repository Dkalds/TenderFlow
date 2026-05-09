"""Tests para dashboard/utils/security.py — validación de URLs."""

from __future__ import annotations

from dashboard.utils.security import safe_url


class TestSafeUrl:
    # ── URLs válidas ─────────────────────────────────────────────────────
    def test_http_valida(self):
        url = "http://example.com/page"
        assert safe_url(url) == url

    def test_https_valida(self):
        url = "https://contrataciondelestado.es/licitacion/123"
        assert safe_url(url) == url

    def test_https_con_query_params(self):
        url = "https://example.com/search?q=sap&page=1"
        assert safe_url(url) == url

    def test_https_con_fragment(self):
        url = "https://example.com/page#section"
        assert safe_url(url) == url

    def test_url_con_espacios_iniciales(self):
        url = "  https://example.com  "
        result = safe_url(url)
        assert result == "https://example.com"

    # ── URLs peligrosas — deben devolver None ───────────────────────────
    def test_javascript_uri(self):
        assert safe_url("javascript:alert('xss')") is None

    def test_javascript_uri_mayusculas(self):
        assert safe_url("JAVASCRIPT:alert(1)") is None

    def test_javascript_con_espacios(self):
        assert safe_url("  javascript:void(0)  ") is None

    def test_data_uri(self):
        assert safe_url("data:text/html,<script>alert(1)</script>") is None

    def test_vbscript_uri(self):
        assert safe_url("vbscript:msgbox('xss')") is None

    def test_file_uri(self):
        assert safe_url("file:///etc/passwd") is None

    def test_ruta_relativa(self):
        assert safe_url("/relative/path") is None

    def test_hash_no_es_url_valida(self):
        # Antes pasaba como autorreferencia válida — ahora se rechaza.
        assert safe_url("#") is None

    # ── Entradas inválidas ───────────────────────────────────────────────
    def test_none_devuelve_none(self):
        assert safe_url(None) is None

    def test_string_vacio_devuelve_none(self):
        assert safe_url("") is None

    def test_no_string_devuelve_none(self):
        assert safe_url(123) is None  # type: ignore[arg-type]

    def test_solo_espacios_devuelve_none(self):
        assert safe_url("   ") is None
