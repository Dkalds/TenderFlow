"""Tests para dashboard/utils/security.py — validación de URLs."""

from __future__ import annotations

import pytest

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


class TestTursoDatabaseUrlValidator:
    """Valida que Settings rechaza esquemas peligrosos en TURSO_DATABASE_URL."""

    def _make_settings(self, monkeypatch, url: str):
        monkeypatch.setenv("TURSO_DATABASE_URL", url)
        monkeypatch.setenv("TURSO_AUTH_TOKEN", "token123" if url else "")
        from config.settings import Settings

        return Settings()

    def test_libsql_scheme_aceptado(self, monkeypatch):
        s = self._make_settings(monkeypatch, "libsql://mydb.turso.io")
        assert s.TURSO_DATABASE_URL == "libsql://mydb.turso.io"

    def test_https_scheme_aceptado(self, monkeypatch):
        s = self._make_settings(monkeypatch, "https://mydb.turso.io")
        assert s.TURSO_DATABASE_URL == "https://mydb.turso.io"

    def test_vacio_aceptado(self, monkeypatch):
        monkeypatch.setenv("TURSO_DATABASE_URL", "")
        monkeypatch.setenv("TURSO_AUTH_TOKEN", "")
        from config.settings import Settings

        s = Settings()
        assert s.TURSO_DATABASE_URL == ""

    def test_file_scheme_rechazado(self, monkeypatch):
        monkeypatch.setenv("TURSO_DATABASE_URL", "file:///etc/passwd")
        monkeypatch.setenv("TURSO_AUTH_TOKEN", "token123")
        from config.settings import Settings
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="esquema no permitido"):
            Settings()

    def test_javascript_scheme_rechazado(self, monkeypatch):
        monkeypatch.setenv("TURSO_DATABASE_URL", "javascript:alert(1)")
        monkeypatch.setenv("TURSO_AUTH_TOKEN", "token123")
        from config.settings import Settings
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="esquema no permitido"):
            Settings()

    def test_http_scheme_rechazado(self, monkeypatch):
        """http:// (sin TLS) no está en la allowlist para Turso."""
        monkeypatch.setenv("TURSO_DATABASE_URL", "http://mydb.turso.io")
        monkeypatch.setenv("TURSO_AUTH_TOKEN", "token123")
        from config.settings import Settings
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="esquema no permitido"):
            Settings()
