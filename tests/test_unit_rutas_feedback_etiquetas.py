"""Quién puede escribir etiquetas de relevancia (2026-09-27).

Una fila de `ml_feedback` con `source='human'` no es una opinión más: manda
sobre las keywords al entrenar los dos clasificadores (prioridad humano > LLM >
keywords). Hasta hoy `POST /api/v1/feedback` aceptaba a cualquier usuario con
sesión, aunque la única pantalla que lo usa —el etiquetado de `/ops`— ya es
solo para admins. Las API keys no tenían ese hueco: el núcleo de validación les
exige el scope `feedback:write` (`api/scopes.py`), que es una concesión
explícita.

Lo que fija este módulo: con sesión, solo un admin escribe etiquetas; una API
key con su scope sigue pudiendo.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

RUTA = "/api/v1/feedback"
_CUERPO = {"expediente": "EXP-1", "relevante": True}


@pytest.fixture
def escrituras(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Sustituye el repositorio y la auditoría; devuelve las filas escritas."""
    import api.routes.feedback as rutas

    filas: list[dict[str, Any]] = []

    def _insert(**kwargs: Any) -> str:
        filas.append(kwargs)
        return "2026-09-27T00:00:00+00:00"

    monkeypatch.setattr(rutas._repo, "insert", _insert)
    monkeypatch.setattr(rutas, "log_event", lambda **kwargs: None)
    return filas


def _cliente(principal: dict[str, Any]) -> Iterator[TestClient]:
    from api.app import app
    from api.routes.dual_auth import require_any_auth

    app.dependency_overrides[require_any_auth] = lambda: principal
    try:
        yield TestClient(app, raise_server_exceptions=True)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def sesion_sin_admin() -> Iterator[TestClient]:
    yield from _cliente({"user_id": 7, "is_admin": False, "auth_method": "session"})


@pytest.fixture
def sesion_admin() -> Iterator[TestClient]:
    yield from _cliente({"user_id": 1, "is_admin": True, "auth_method": "session"})


@pytest.fixture
def api_key_con_scope() -> Iterator[TestClient]:
    yield from _cliente(
        {"user_id": 9, "is_admin": False, "auth_method": "api_key", "scopes": ["feedback:write"]}
    )


def test_con_sesion_un_usuario_sin_admin_no_escribe_etiquetas(
    sesion_sin_admin: TestClient, escrituras: list[dict[str, Any]]
) -> None:
    respuesta = sesion_sin_admin.post(RUTA, json=_CUERPO)
    assert respuesta.status_code == 403
    assert escrituras == []


def test_con_sesion_un_admin_escribe_etiquetas(
    sesion_admin: TestClient, escrituras: list[dict[str, Any]]
) -> None:
    respuesta = sesion_admin.post(RUTA, json=_CUERPO)
    assert respuesta.status_code == 201
    assert [fila["expediente"] for fila in escrituras] == ["EXP-1"]


def test_una_api_key_con_su_scope_sigue_escribiendo(
    api_key_con_scope: TestClient, escrituras: list[dict[str, Any]]
) -> None:
    respuesta = api_key_con_scope.post(RUTA, json=_CUERPO)
    assert respuesta.status_code == 201
    assert len(escrituras) == 1
