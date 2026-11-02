"""Quién puede escribir etiquetas de relevancia (2026-09-27).

Una fila de `ml_feedback` con `source='revision_ti'` (`'human'` para las
filas anteriores al plan de clasificación en tres niveles) no es una opinión
más: manda sobre las keywords al entrenar los dos clasificadores (prioridad
humano > LLM > keywords), y esos modelos los comparten todas las organizaciones.
Hasta 2026-09 `POST /api/v1/feedback` aceptaba a cualquier usuario con sesión; se
cerró para las sesiones, pero se dejó abierto para las API keys bajo el supuesto
de que `feedback:write` era «una concesión explícita». No lo es: cualquier
usuario acuña ese scope con `POST /me/keys` (solo `admin` y `*` están
reservados), así que bastaba una clave para escribir miles de etiquetas falsas
(auditoría 2026-11, authz-usuario-rutas-1).

Lo que fija este módulo: escribe etiquetas un admin con sesión, o una API key
con scope `feedback:write` **cuyo dueño es admin hoy**. No hace falta que la
clave lleve el scope `admin`: `scripts/muestra_etiquetado_ti.py` usa una clave
de scope estrecho.
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

    async def _id_vigente(id_licitacion: str, _response: Any) -> str:
        return id_licitacion  # sin BD: ningún id es un alias

    monkeypatch.setattr(rutas._repo, "insert", _insert)
    monkeypatch.setattr(rutas, "log_event", lambda **kwargs: None)
    monkeypatch.setattr(rutas, "id_vigente", _id_vigente)
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
def api_key_de_usuario_sin_admin() -> Iterator[TestClient]:
    """Lo que acuña cualquier usuario: `feedback:write` sobre una cuenta normal."""
    yield from _cliente(
        {
            "user_id": 9,
            "is_admin": False,
            "owner_is_admin": False,
            "auth_method": "api_key",
            "scopes": frozenset({"feedback:write"}),
        }
    )


@pytest.fixture
def api_key_de_admin_con_scope_estrecho() -> Iterator[TestClient]:
    """La de `muestra_etiquetado_ti.py`: dueño admin, sin el scope `admin`."""
    yield from _cliente(
        {
            "user_id": 1,
            "is_admin": False,
            "owner_is_admin": True,
            "auth_method": "api_key",
            "scopes": frozenset({"feedback:write"}),
        }
    )


@pytest.fixture
def api_key_comodin_de_usuario_sin_admin() -> Iterator[TestClient]:
    """Un `*` no convierte en admin a una cuenta que no lo es."""
    yield from _cliente(
        {
            "user_id": 9,
            "is_admin": False,
            "owner_is_admin": False,
            "auth_method": "api_key",
            "scopes": frozenset({"*"}),
        }
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


def test_una_api_key_de_un_usuario_sin_admin_no_escribe_etiquetas(
    api_key_de_usuario_sin_admin: TestClient, escrituras: list[dict[str, Any]]
) -> None:
    """El caso de la auditoría: `POST /me/keys` con `feedback:write` y luego
    miles de etiquetas `revision_ti` falsas que entrenan el modelo de todos."""
    respuesta = api_key_de_usuario_sin_admin.post(RUTA, json=_CUERPO)
    assert respuesta.status_code == 403
    assert escrituras == []


def test_una_api_key_comodin_de_un_usuario_sin_admin_tampoco(
    api_key_comodin_de_usuario_sin_admin: TestClient, escrituras: list[dict[str, Any]]
) -> None:
    respuesta = api_key_comodin_de_usuario_sin_admin.post(RUTA, json=_CUERPO)
    assert respuesta.status_code == 403
    assert escrituras == []


def test_una_api_key_de_admin_con_su_scope_sigue_escribiendo(
    api_key_de_admin_con_scope_estrecho: TestClient, escrituras: list[dict[str, Any]]
) -> None:
    respuesta = api_key_de_admin_con_scope_estrecho.post(RUTA, json=_CUERPO)
    assert respuesta.status_code == 201
    assert [fila["user_id"] for fila in escrituras] == [1]
    assert escrituras[0]["source"] == "revision_ti"


def test_la_revision_se_guarda_como_revision_ti(
    sesion_admin: TestClient, escrituras: list[dict[str, Any]]
) -> None:
    """Desde el plan de tres niveles, `relevante` significa «es TI». Las filas
    viejas (`human`) significaban «es SAP» y no se mezclan con las nuevas."""
    sesion_admin.post(RUTA, json=_CUERPO)
    assert escrituras[0]["source"] == "revision_ti"


def test_el_contrato_dice_que_relevante_es_es_ti() -> None:
    """La descripción del campo es contrato (OpenAPI → ``api.d.ts``): decía
    «relevante», que era «es SAP» hasta el plan de tres niveles."""
    from api.app import app

    campo = app.openapi()["components"]["schemas"]["FeedbackRequest"]["properties"]["relevante"]

    assert "es TI" in campo["description"]
    assert "es relevante" not in campo["description"]
