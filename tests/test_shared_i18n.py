"""Tests para shared/i18n.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch


class TestI18n:
    def setup_method(self):
        import shared.i18n as mod

        self._mod = mod
        mod.set_locale("es")
        mod._load.cache_clear()

    def test_set_locale_supported(self):
        self._mod.set_locale("en")
        assert self._mod.get_locale() == "en"

    def test_set_locale_unsupported_falls_back(self):
        self._mod.set_locale("fr")
        assert self._mod.get_locale() == "es"

    def test_supported_locales(self):
        assert self._mod.supported_locales() == ("es", "en")

    def test_t_returns_key_when_no_translation(self):
        with patch.object(self._mod, "_load", return_value={}):
            result = self._mod.t("nonexistent.key")
        assert result == "nonexistent.key"

    def test_t_with_kwargs(self):
        with patch.object(self._mod, "_load", return_value={"greet": "Hola {name}"}):
            result = self._mod.t("greet", name="World")
        assert result == "Hola World"

    def test_t_format_error_returns_template(self):
        with patch.object(self._mod, "_load", return_value={"bad": "{missing}"}):
            result = self._mod.t("bad", wrong="val")
        assert result == "{missing}"

    def test_t_fallback_to_es(self):
        self._mod.set_locale("en")

        # en returns empty, es has the key
        def fake_load(locale):
            if locale == "en":
                return {}
            return {"only_es": "valor_es"}

        with patch.object(self._mod, "_load", side_effect=fake_load):
            result = self._mod.t("only_es")
        assert result == "valor_es"

    def test_load_missing_file(self):
        self._mod._load.cache_clear()
        with patch.object(Path, "is_file", return_value=False):
            result = self._mod._load.__wrapped__("xx")
        assert result == {}

    def test_load_json_error(self):
        self._mod._load.cache_clear()
        with patch.object(Path, "is_file", return_value=True):
            with patch.object(Path, "read_text", side_effect=ValueError("bad json")):
                result = self._mod._load.__wrapped__("zz")
        assert result == {}

    def test_load_valid_json(self):
        self._mod._load.cache_clear()
        with patch.object(Path, "is_file", return_value=True):
            with patch.object(Path, "read_text", return_value='{"k":"v"}'):
                result = self._mod._load.__wrapped__("qq")
        assert result == {"k": "v"}

    def test_t_same_locale_no_fallback_dict(self):
        """When active locale == default, fallback dict should be empty."""
        self._mod.set_locale("es")
        with patch.object(self._mod, "_load", return_value={"a": "b"}):
            result = self._mod.t("a")
        assert result == "b"
