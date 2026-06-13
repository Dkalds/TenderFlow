"""Tests para validación de TURSO_DATABASE_URL."""

from __future__ import annotations

import pytest


class TestTursoDatabaseUrlValidator:
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
        from pydantic import ValidationError

        from config.settings import Settings

        with pytest.raises(ValidationError, match="esquema no permitido"):
            Settings()

    def test_javascript_scheme_rechazado(self, monkeypatch):
        monkeypatch.setenv("TURSO_DATABASE_URL", "javascript:alert(1)")
        monkeypatch.setenv("TURSO_AUTH_TOKEN", "token123")
        from pydantic import ValidationError

        from config.settings import Settings

        with pytest.raises(ValidationError, match="esquema no permitido"):
            Settings()

    def test_http_scheme_rechazado(self, monkeypatch):
        monkeypatch.setenv("TURSO_DATABASE_URL", "http://mydb.turso.io")
        monkeypatch.setenv("TURSO_AUTH_TOKEN", "token123")
        from pydantic import ValidationError

        from config.settings import Settings

        with pytest.raises(ValidationError, match="esquema no permitido"):
            Settings()
