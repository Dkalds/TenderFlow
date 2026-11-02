"""Lo que una API key ya no puede hacer sola (auditoría 2026-11).

Sin Postgres: la autenticación se sustituye con `dependency_overrides` y los
servicios con `monkeypatch`, de modo que lo que se ejercita es lo que cada ruta
aporta, que es justo lo que estos hallazgos endurecen.

- `authz-organizaciones-3`: traspasar la propiedad y asignar un owner exigen
  sesión reciente; una API key (da igual el scope) no sirve.
- `authz-usuario-rutas-5`: `exports:read` no basta para llevarse el tablero.
- `authz-usuario-rutas-1`: la ctx de una API key lleva el rol vigente del dueño.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import BackgroundTasks
from fastapi.testclient import TestClient

_TRASPASO = "/api/v1/organizations/1/transfer-ownership"
_MIEMBRO = "/api/v1/organizations/1/members/9"


def _sesion_reciente() -> dict[str, Any]:
    return {
        "user_id": 5,
        "scopes": ["*"],
        "auth_method": "session",
        "authenticated_at": datetime.now(UTC).isoformat(),
        "mfa_required": False,
    }


def _api_key(*scopes: str) -> dict[str, Any]:
    return {
        "user_id": 5,
        "api_key_id": 3,
        "is_admin": False,
        "auth_method": "api_key",
        "scopes": frozenset(scopes),
    }


def _cliente(principal: dict[str, Any]) -> Iterator[TestClient]:
    from api.app import app
    from api.routes.dual_auth import require_any_auth

    app.dependency_overrides[require_any_auth] = lambda: principal
    try:
        yield TestClient(app, raise_server_exceptions=True)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def como_api_key_de_todo() -> Iterator[TestClient]:
    """Ni el comodín `*` sustituye a una sesión reciente."""
    yield from _cliente(_api_key("*", "organizations:manage", "pursuits:write"))


@pytest.fixture
def como_sesion_vieja() -> Iterator[TestClient]:
    ctx = {
        **_sesion_reciente(),
        "authenticated_at": (datetime.now(UTC) - timedelta(days=2)).isoformat(),
    }
    yield from _cliente(ctx)


@pytest.fixture
def como_sesion_reciente() -> Iterator[TestClient]:
    yield from _cliente(_sesion_reciente())


@pytest.fixture
def servicios_de_equipo(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """Sustituye los servicios y la auditoría; devuelve lo que se llegó a llamar."""
    import api.routes.organizations as rutas
    from services.organizations import OrganizationPermissionError

    llamadas: dict[str, list[Any]] = {"traspasos": [], "miembros": []}

    def _traspasar(**kwargs: Any) -> None:
        llamadas["traspasos"].append(kwargs)

    def _upsert(*args: Any, **_kwargs: Any) -> Any:
        llamadas["miembros"].append(args)
        raise OrganizationPermissionError("llegó al servicio")

    async def _sin_auditoria(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(rutas, "transferir_propiedad", _traspasar)
    monkeypatch.setattr(rutas, "upsert_membership", _upsert)
    monkeypatch.setattr(rutas, "_auditar_organizacion", _sin_auditoria)
    return llamadas


# ── Traspaso y asignación de owner ───────────────────────────────────────────


def test_una_api_key_no_traspasa_la_propiedad(
    como_api_key_de_todo: TestClient, servicios_de_equipo: dict[str, list[Any]]
) -> None:
    respuesta = como_api_key_de_todo.post(_TRASPASO, json={"nuevo_owner_user_id": 9})

    assert respuesta.status_code == 403
    assert servicios_de_equipo["traspasos"] == []


def test_una_sesion_vieja_no_traspasa_la_propiedad(
    como_sesion_vieja: TestClient, servicios_de_equipo: dict[str, list[Any]]
) -> None:
    respuesta = como_sesion_vieja.post(_TRASPASO, json={"nuevo_owner_user_id": 9})

    assert respuesta.status_code == 403
    assert servicios_de_equipo["traspasos"] == []


def test_una_sesion_reciente_si_traspasa(
    como_sesion_reciente: TestClient, servicios_de_equipo: dict[str, list[Any]]
) -> None:
    respuesta = como_sesion_reciente.post(_TRASPASO, json={"nuevo_owner_user_id": 9})

    assert respuesta.status_code == 200
    assert len(servicios_de_equipo["traspasos"]) == 1


def test_una_api_key_no_asigna_un_owner(
    como_api_key_de_todo: TestClient, servicios_de_equipo: dict[str, list[Any]]
) -> None:
    """Un owner añadido no se puede degradar (`_guard_owner_row`): es la toma
    de propiedad irrevocable de `authz-organizaciones-3`."""
    respuesta = como_api_key_de_todo.put(
        _MIEMBRO, json={"user_id": 9, "role": "owner", "status": "active"}
    )

    assert respuesta.status_code == 403
    assert servicios_de_equipo["miembros"] == []


def test_una_sesion_vieja_no_asigna_un_owner(
    como_sesion_vieja: TestClient, servicios_de_equipo: dict[str, list[Any]]
) -> None:
    respuesta = como_sesion_vieja.put(
        _MIEMBRO, json={"user_id": 9, "role": "owner", "status": "active"}
    )

    assert respuesta.status_code == 403
    assert servicios_de_equipo["miembros"] == []


def test_una_sesion_reciente_llega_al_servicio_al_asignar_un_owner(
    como_sesion_reciente: TestClient, servicios_de_equipo: dict[str, list[Any]]
) -> None:
    respuesta = como_sesion_reciente.put(
        _MIEMBRO, json={"user_id": 9, "role": "owner", "status": "active"}
    )

    assert respuesta.status_code == 403
    assert respuesta.json()["detail"] == "llegó al servicio"
    assert len(servicios_de_equipo["miembros"]) == 1


def test_gestionar_miembros_que_no_son_owner_no_pide_sesion_reciente(
    como_api_key_de_todo: TestClient, servicios_de_equipo: dict[str, list[Any]]
) -> None:
    """Los roles `admin`/`member`/`viewer` siguen al alcance de una clave con
    `organizations:manage`: el endurecimiento es solo para el owner."""
    respuesta = como_api_key_de_todo.put(
        _MIEMBRO, json={"user_id": 9, "role": "admin", "status": "active"}
    )

    assert respuesta.json()["detail"] == "llegó al servicio"
    assert len(servicios_de_equipo["miembros"]) == 1


# ── Exportar el tablero ──────────────────────────────────────────────────────


def test_exports_read_no_basta_para_exportar_el_tablero_a_un_crm() -> None:
    from api.app import app
    from api.routes.dual_auth import require_any_auth

    app.dependency_overrides[require_any_auth] = lambda: _api_key("exports:read")
    try:
        respuesta = TestClient(app, raise_server_exceptions=True).get("/api/v1/exports/crm")
    finally:
        app.dependency_overrides.clear()

    assert respuesta.status_code == 403
    assert "pursuits:read" in respuesta.json()["detail"]


def test_exports_read_no_basta_para_descargar_el_tablero() -> None:
    from api.app import app
    from api.routes.dual_auth import require_any_auth

    app.dependency_overrides[require_any_auth] = lambda: _api_key("exports:read")
    try:
        respuesta = TestClient(app, raise_server_exceptions=True).get(
            "/api/v1/exports/download", params={"recurso": "pursuits", "format": "csv"}
        )
    finally:
        app.dependency_overrides.clear()

    assert respuesta.status_code == 403
    assert "pursuits:read" in respuesta.json()["detail"]


def test_la_exportacion_de_licitaciones_no_pide_pursuits_read() -> None:
    """El helper solo se aplica al tablero; la descarga del corpus público no
    cambia."""
    from api.routes.exports import _exigir_lectura_del_tablero

    _exigir_lectura_del_tablero(_api_key("exports:read", "pursuits:read"))
    _exigir_lectura_del_tablero(_api_key("*"))
    _exigir_lectura_del_tablero(_sesion_reciente())  # una sesión no lleva scopes


def test_el_tablero_exportado_pide_pursuits_read_a_la_api_key() -> None:
    from fastapi import HTTPException

    from api.routes.exports import _exigir_lectura_del_tablero

    with pytest.raises(HTTPException) as exc:
        _exigir_lectura_del_tablero(_api_key("exports:read", "data:read"))
    assert exc.value.status_code == 403


# ── La ctx de una API key lleva el rol vigente de su dueño ───────────────────


def _ctx_de_api_key(
    monkeypatch: pytest.MonkeyPatch, scopes: frozenset[str], *, dueno_admin: bool
) -> dict[str, Any]:
    import api.auth as auth_mod
    from api.auth import AuthContext
    from api.routes.dual_auth import require_any_auth

    async def _validar(*_a: Any, **_k: Any) -> AuthContext:
        return AuthContext(
            key_hash="h",
            key_id=3,
            scopes=scopes,
            user_id=7,
            owner={"email": "dueno@example.test", "display_name": "D", "is_admin": dueno_admin},
        )

    monkeypatch.setattr(auth_mod, "validate_api_key_credential", _validar)
    peticion: Any = SimpleNamespace(method="POST", url=SimpleNamespace(path="/api/v1/feedback"))
    return asyncio.run(
        require_any_auth(
            request=peticion,
            api_key_raw="k",
            session=None,
            x_csrf_token=None,
            background_tasks=BackgroundTasks(),
        )
    )


def test_una_clave_de_scope_estrecho_de_un_admin_conserva_el_rol_del_dueno(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _ctx_de_api_key(monkeypatch, frozenset({"feedback:write"}), dueno_admin=True)

    assert ctx["owner_is_admin"] is True
    assert ctx["is_admin"] is False  # sin el scope `admin`, la clave no administra


def test_una_clave_con_scope_admin_de_un_admin_es_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _ctx_de_api_key(monkeypatch, frozenset({"admin"}), dueno_admin=True)

    assert ctx["owner_is_admin"] is True
    assert ctx["is_admin"] is True


def test_un_comodin_no_hace_admin_a_quien_no_lo_es(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _ctx_de_api_key(monkeypatch, frozenset({"*"}), dueno_admin=False)

    assert ctx["owner_is_admin"] is False
    assert ctx["is_admin"] is False
