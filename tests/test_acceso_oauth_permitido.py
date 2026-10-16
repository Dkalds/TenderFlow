"""``services.access_grants.acceso_oauth_permitido``: allowlist estática o concesión dinámica.

Es la única definición de «esta dirección puede entrar por OAuth»: la usan el
callback de la API (``api/routes/auth.py::_oauth_access_allowed``) y el login
del MCP interno. Cualquier fallo de la mitad dinámica deniega.
"""

from __future__ import annotations

from typing import Any

import pytest

from services import access_grants
from services.access_grants import acceso_oauth_permitido


def _no_debe_consultar(_email: str) -> bool:
    raise AssertionError("con la lista estática bastaba: no debía consultar access_grants")


def test_la_lista_estatica_basta_sin_tocar_la_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(access_grants, "oauth_email_allowed", lambda _email: True)
    monkeypatch.setattr("db.access_grants.is_access_granted", _no_debe_consultar)
    assert acceso_oauth_permitido("ana@empresa.example") is True


def test_la_concesion_dinamica_deja_entrar(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(access_grants, "oauth_email_allowed", lambda _email: False)
    monkeypatch.setattr(
        "db.access_grants.is_access_granted", lambda email: email == "ana@empresa.example"
    )
    assert acceso_oauth_permitido("ana@empresa.example") is True
    assert acceso_oauth_permitido("otra@empresa.example") is False


def test_acceso_oauth_permitido_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(access_grants, "oauth_email_allowed", lambda _email: False)
    llamadas: list[Any] = []

    def _caida(email: str) -> bool:
        llamadas.append(email)
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("db.access_grants.is_access_granted", _caida)
    assert acceso_oauth_permitido("nadie@empresa.example") is False
    assert llamadas == ["nadie@empresa.example"]
