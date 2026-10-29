"""Configuración y capa del servidor MCP interno (``mcp_server/``)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from config.settings import (
    mcp_database_url,
    mcp_google_redirect_uri,
    mcp_public_url,
    mcp_redirect_uris_extra,
)

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_layers.py"


def _cargar_check_layers() -> ModuleType:
    """``scripts/`` no es un paquete: se carga el fichero, como en el ratchet de capas."""
    spec = importlib.util.spec_from_file_location("check_layers", _SCRIPT)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["check_layers"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def test_mcp_config_vacia_por_defecto(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("MCP_DATABASE_URL", "MCP_PUBLIC_URL", "MCP_GOOGLE_REDIRECT_URI"):
        monkeypatch.delenv(var, raising=False)
    assert mcp_database_url() == ""
    assert mcp_public_url() == ""
    assert mcp_google_redirect_uri() == ""


def test_mcp_public_url_sin_barra_final(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_PUBLIC_URL", "https://mcp.example.com/ ")
    assert mcp_public_url() == "https://mcp.example.com"


def test_mcp_database_url_y_redirect_se_recortan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_DATABASE_URL", "  postgresql://u:p@h/db  ")
    monkeypatch.setenv("MCP_GOOGLE_REDIRECT_URI", " https://mcp.example.com/google/callback ")
    assert mcp_database_url() == "postgresql://u:p@h/db"
    assert mcp_google_redirect_uri() == "https://mcp.example.com/google/callback"


def test_mcp_redirect_uris_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MCP_REDIRECT_URIS_EXTRA", raising=False)
    assert mcp_redirect_uris_extra() == ()
    monkeypatch.setenv("MCP_REDIRECT_URIS_EXTRA", " , ")
    assert mcp_redirect_uris_extra() == ()
    monkeypatch.setenv(
        "MCP_REDIRECT_URIS_EXTRA",
        " https://chatgpt.com/connector/oauth/abc ,https://otro.example/cb,",
    )
    assert mcp_redirect_uris_extra() == (
        "https://chatgpt.com/connector/oauth/abc",
        "https://otro.example/cb",
    )


def test_mcp_server_capa_por_encima_de_api() -> None:
    capas = _cargar_check_layers()
    assert capas.CAPAS[-1] == "mcp_server" and capas.CAPAS[-2] == "api"
    assert ("mcp_server", "api") in capas.PROHIBIDAS
    assert ("mcp_server", "scraper") in capas.PROHIBIDAS


def test_mcp_redirect_uris_extra_se_normalizan_como_pydantic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El DCR compara contra ``str(AnyUrl(...))``: sin normalizar, ``https://Chatgpt.COM`` no casaría."""
    from pydantic import AnyUrl

    from mcp_server.auth.proveedor import redirect_uri_admitido

    monkeypatch.setenv(
        "MCP_REDIRECT_URIS_EXTRA",
        "https://Chatgpt.COM, no es una url ,https://otro.example/cb",
    )
    with pytest.warns(UserWarning, match="MCP_REDIRECT_URIS_EXTRA"):
        extra = mcp_redirect_uris_extra()
    assert extra == ("https://chatgpt.com/", "https://otro.example/cb")
    monkeypatch.setenv("MCP_REDIRECT_URIS_EXTRA", "https://Chatgpt.COM")
    assert redirect_uri_admitido(str(AnyUrl("https://chatgpt.com")))


def test_main_silencia_el_eco_de_errores_del_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    """El SDK repite a INFO el texto de cada error de tool; el arranque lo sube a WARNING."""
    import logging

    from mcp_server import __main__ as arranque

    sdk = logging.getLogger(arranque.LOGGER_ERRORES_SDK)
    monkeypatch.setattr(arranque, "configure_logging", lambda: None)
    monkeypatch.setattr(arranque, "validar_configuracion", list)
    monkeypatch.setattr(arranque, "crear_app", object)
    monkeypatch.setattr(arranque.uvicorn, "run", lambda *a, **k: None)
    previo = sdk.level
    try:
        sdk.setLevel(logging.NOTSET)
        arranque.main()
        assert not sdk.isEnabledFor(logging.INFO)
        assert sdk.isEnabledFor(logging.ERROR)
    finally:
        sdk.setLevel(previo)
