"""Internacionalización (i18n) compartida entre dashboard y API (F5).

API mínima inspirada en gettext::

    from shared.i18n import t, set_locale

    set_locale("en")          # o "es" (default)
    t("dashboard.title")      # → "SAP Public-Sector Tenders"

Las traducciones residen en ficheros JSON planos (clave → string) por
locale en ``shared/i18n_<locale>.json``. Si una clave falta en el locale
activo, se cae a ``es`` y, si tampoco existe, se devuelve la propia
clave (útil para detectar gaps).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

_DEFAULT_LOCALE = "es"
_SUPPORTED = ("es", "en")
_HERE = Path(__file__).resolve().parent

_active_locale: str = _DEFAULT_LOCALE


@lru_cache(maxsize=8)
def _load(locale: str) -> dict[str, str]:
    path = _HERE / f"i18n_{locale}.json"
    if not path.is_file():
        return {}
    try:
        return cast(dict[str, str], json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}


def set_locale(locale: str) -> None:
    """Cambia el locale activo. Si no es soportado, vuelve al default."""
    global _active_locale
    _active_locale = locale if locale in _SUPPORTED else _DEFAULT_LOCALE


def get_locale() -> str:
    return _active_locale


def supported_locales() -> tuple[str, ...]:
    return _SUPPORTED


def t(key: str, **kwargs: Any) -> str:
    """Traduce ``key`` aplicando ``str.format(**kwargs)`` opcional.

    Cascada de fallback: locale activo → ``es`` → la propia clave.
    """
    primary = _load(_active_locale)
    fallback = _load(_DEFAULT_LOCALE) if _active_locale != _DEFAULT_LOCALE else {}
    template = primary.get(key) or fallback.get(key) or key
    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError):
            return template
    return template


__all__ = ["get_locale", "set_locale", "supported_locales", "t"]
