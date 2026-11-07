"""Configuración del servidor MCP interno (``mcp_server/``).

Sale de ``config/settings.py`` (P3 «Los dos módulos-dios») y ``config.settings``
la reexporta, así que ``from config.settings import mcp_database_url`` sigue
valiendo.
"""

from __future__ import annotations

import os
import warnings

from pydantic import AnyUrl

from config.settings_bd import _LOCAL_DB_HOSTS, _extract_host, _extract_sslmode

# ── Servidor MCP interno (mcp_server/) ───────────────────────────────────────
# Funciones y no campos de ``Settings``, como ``oauth_microsoft_*``: que falten
# no debe abortar la API en ``prod``. Quien valida que estén es el arranque del
# MCP, que es el único que las necesita.


def mcp_database_url() -> str:
    """``MCP_DATABASE_URL`` — DSN del rol ``tenderflow_mcp`` (solo lectura)."""
    return os.environ.get("MCP_DATABASE_URL", "").strip()


def mcp_database_ssl_problema() -> str | None:
    """Por qué ``MCP_DATABASE_URL`` no cumple la política de TLS de ``DATABASE_URL``, o ``None``.

    Es la de ``Settings._validate_prod_database_ssl`` (que solo mira
    ``DATABASE_URL``): en prod/staging, o con un host remoto, hace falta un
    ``sslmode`` que garantice TLS (``require`` o más; ``verify-full`` es lo que
    pide el runbook). Sin él libpq usa ``prefer`` y un atacante en la red
    (MITM) entre el servicio y el pooler lee el SQL y los datos. Vacío no es
    problema de TLS: de eso se queja ``validar_configuracion``.
    """
    # Import diferido: `config.settings` importa este módulo para reexportarlo.
    from config.settings import settings

    url = mcp_database_url()
    if not url:
        return None
    if settings.ENV not in ("prod", "staging") and _extract_host(url) in _LOCAL_DB_HOSTS:
        return None
    sslmode = _extract_sslmode(url)
    if sslmode is None or sslmode in ("disable", "allow", "prefer"):
        return "MCP_DATABASE_URL (sslmode=verify-full o, como mínimo, require)"
    return None


def mcp_public_url() -> str:
    """``MCP_PUBLIC_URL`` — URL pública del servidor MCP, sin barra final."""
    return os.environ.get("MCP_PUBLIC_URL", "").strip().rstrip("/")


def mcp_google_redirect_uri() -> str:
    """``MCP_GOOGLE_REDIRECT_URI`` — callback de Google registrado para el MCP."""
    return os.environ.get("MCP_GOOGLE_REDIRECT_URI", "").strip()


def mcp_redirect_uris_extra() -> tuple[str, ...]:
    """``MCP_REDIRECT_URIS_EXTRA`` — redirect URIs exactos que el DCR del MCP admite además.

    Separados por comas; vacío → ``()``. Para clientes con callback propio por
    app, como ChatGPT (``https://chatgpt.com/connector/oauth/{callback_id}``).
    Los de claude.ai/claude.com y el loopback ya están en el proveedor.

    Cada entrada se normaliza como ``pydantic.AnyUrl`` (host en minúsculas,
    ``/`` como ruta vacía), que es la forma en que el DCR recibe el
    ``redirect_uri`` del cliente: sin eso, ``https://Chatgpt.COM`` nunca casaría.
    Una entrada que no es una URL se descarta con un aviso.
    """
    crudo = os.environ.get("MCP_REDIRECT_URIS_EXTRA", "")
    normalizadas: list[str] = []
    for entrada in (uri.strip() for uri in crudo.split(",")):
        if not entrada:
            continue
        try:
            normalizadas.append(str(AnyUrl(entrada)))
        except ValueError:  # pydantic.ValidationError hereda de ValueError
            warnings.warn(
                f"MCP_REDIRECT_URIS_EXTRA: se ignora {entrada!r}, no es una URL válida.",
                UserWarning,
                stacklevel=2,
            )
    return tuple(normalizadas)
