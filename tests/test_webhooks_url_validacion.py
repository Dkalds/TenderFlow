"""Validación de la URL de un webhook: fuera del event loop, tras el rol y sin oráculo.

El ``field_validator`` del cuerpo resolvía el host con ``getaddrinfo`` síncrono
en el event loop, antes de comprobar que quien llama es owner/admin, y el
motivo del ``ValueError`` de ``shared.ssrf`` salía en el 422: cualquiera con
cuenta podía sondear qué nombres resuelven a la red interna.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from api.app import app
from api.routes.dual_auth import require_any_auth
from db.repositories.organizations import OrganizationRepository

_URL = "https://interno.example.test/hook"
_MOTIVO = "Host resuelve a una dirección no global"
_HASH = "test-hash"  # pragma: allowlist secret


class _Resolver:
    """Doble de ``validate_outbound_url``: apunta si corrió en el event loop."""

    def __init__(self) -> None:
        self.rechazar = True
        self.en_el_loop: list[bool] = []

    def __call__(self, url: str, **_: Any) -> str:
        try:
            asyncio.get_running_loop()
            self.en_el_loop.append(True)
        except RuntimeError:
            self.en_el_loop.append(False)
        if self.rechazar:
            raise ValueError(_MOTIVO)
        return url


@pytest.fixture()
def resolver(monkeypatch: pytest.MonkeyPatch) -> Any:
    doble = _Resolver()
    monkeypatch.setattr("api.routes.webhooks.validate_outbound_url", doble)
    yield doble
    app.dependency_overrides.clear()


def _como(user_id: int) -> None:
    app.dependency_overrides[require_any_auth] = lambda: {
        "user_id": user_id,
        "auth_method": "session",
        "user_key": f"user-{user_id}",
        "email": f"u{user_id}@example.test",
        "is_admin": False,
    }


def _equipo(nombre: str) -> tuple[int, int]:
    """Usuario owner de una organización compartida. Devuelve ``(user_id, org_id)``."""
    from db.users import create_user

    owner = create_user(email=f"{nombre}@example.test", password_hash=_HASH)
    return owner, int(OrganizationRepository().create_organization(nombre, owner)["id"])


def _crear(client: Any, organization_id: int) -> Any:
    return client.post(
        "/api/v1/webhooks",
        json={"name": "x", "url": _URL, "event_types": ["*"], "organization_id": organization_id},
    )


def test_el_rechazo_ssrf_es_un_422_generico_y_resuelve_fuera_del_loop(
    client: Any, api_db: Any, resolver: _Resolver
) -> None:
    owner, org = _equipo("wh-url-alta")
    _como(owner)

    respuesta = _crear(client, org)

    assert respuesta.status_code == 422, respuesta.text
    assert _MOTIVO not in respuesta.text
    assert resolver.en_el_loop == [False], "getaddrinfo no puede correr en el event loop"


def test_el_patch_tambien_valida_fuera_del_loop_y_sin_motivo(
    client: Any, api_db: Any, resolver: _Resolver
) -> None:
    owner, org = _equipo("wh-url-patch")
    _como(owner)
    resolver.rechazar = False
    webhook_id = _crear(client, org).json()["id"]
    resolver.rechazar = True
    resolver.en_el_loop.clear()

    respuesta = client.patch(
        f"/api/v1/webhooks/{webhook_id}",
        params={"organization_id": org},
        json={"url": "https://otro.example.test/hook"},
    )

    assert respuesta.status_code == 422, respuesta.text
    assert _MOTIVO not in respuesta.text
    assert resolver.en_el_loop == [False]


def test_un_miembro_sin_rol_de_gestion_no_llega_a_resolver(
    client: Any, api_db: Any, resolver: _Resolver
) -> None:
    from db.users import create_user

    _owner, org = _equipo("wh-url-rol")
    miembro = create_user(email="wh-url-miembro@example.test", password_hash=_HASH)
    OrganizationRepository().add_membership(org, miembro, "member")
    _como(miembro)

    respuesta = _crear(client, org)

    assert respuesta.status_code == 403, respuesta.text
    assert resolver.en_el_loop == []
