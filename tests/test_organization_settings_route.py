"""``/organizations/{id}/settings`` por HTTP: quién lee, quién escribe y qué responde.

``tests/test_unit_organization_settings_service.py`` fija la lógica del servicio
con dobles. Aquí se fija lo que sólo ve la ruta: cómo se traduce cada excepción
a un código (403 para quien no es miembro o no administra, 422 para una familia
que no existe) y que el cambio aceptado queda guardado y en la auditoría.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from api.routes.dual_auth import require_any_auth
from db.database import connect_read
from db.repositories.organizations import OrganizationRepository
from services.organizations import get_settings
from shared.audit_events import ORG_SETTINGS_UPDATED


def _user(email: str) -> int:
    from db.users import create_user

    return create_user(
        email=email,
        password_hash="test-hash",  # pragma: allowlist secret
        display_name=email.split("@")[0],
    )


@pytest.fixture()
def equipo(api_db) -> dict[str, int]:
    owner = _user("settings-owner@example.test")
    member = _user("settings-member@example.test")
    outsider = _user("settings-outsider@example.test")
    organizations = OrganizationRepository()
    org = int(organizations.create_organization("Equipo con ajustes", owner)["id"])
    organizations.add_membership(org, member, "member")
    return {"owner": owner, "member": member, "outsider": outsider, "org": org}


@pytest.fixture()
def como() -> Iterator[Any]:
    """Cambia quién llama: ``como(user_id)`` antes de cada petición."""
    from api.app import app

    def _como(user_id: int) -> None:
        app.dependency_overrides[require_any_auth] = lambda: {
            "user_id": user_id,
            "auth_method": "session",
            "user_key": f"settings-test-{user_id}",
        }

    try:
        yield _como
    finally:
        app.dependency_overrides.pop(require_any_auth, None)


def _url(org: int) -> str:
    return f"/api/v1/organizations/{org}/settings"


def _una_familia(owner: int, org: int) -> str:
    disponibles = get_settings(owner, org).tecnologias_disponibles
    assert disponibles, "el diccionario no tiene familias: el test no mediría nada"
    return disponibles[0]


def test_un_miembro_lee_la_configuracion(client, equipo, como) -> None:
    como(equipo["member"])

    respuesta = client.get(_url(equipo["org"]))

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["organization_id"] == equipo["org"]
    assert cuerpo["tecnologias"] == []
    assert cuerpo["tecnologias_disponibles"]


def test_quien_no_es_miembro_no_la_lee(client, equipo, como) -> None:
    como(equipo["outsider"])

    assert client.get(_url(equipo["org"])).status_code == 403


@pytest.mark.parametrize("quien", ["member", "outsider"])
def test_solo_owner_o_admin_la_cambian(client, equipo, como, quien) -> None:
    familia = _una_familia(equipo["owner"], equipo["org"])
    como(equipo[quien])

    respuesta = client.put(_url(equipo["org"]), json={"tecnologias": [familia]})

    assert respuesta.status_code == 403
    assert get_settings(equipo["owner"], equipo["org"]).tecnologias == []


def test_una_familia_que_no_existe_es_422_y_no_se_guarda(client, equipo, como) -> None:
    como(equipo["owner"])

    respuesta = client.put(_url(equipo["org"]), json={"tecnologias": ["NO-EXISTE"]})

    assert respuesta.status_code == 422
    assert "NO-EXISTE" in respuesta.json()["detail"]
    assert get_settings(equipo["owner"], equipo["org"]).tecnologias == []


def test_un_campo_que_el_contrato_no_conoce_es_422(client, equipo, como) -> None:
    """``extra="forbid"``: una clave mal escrita no puede devolver 200 sin
    haber guardado lo que el administrador creía estar guardando."""
    como(equipo["owner"])

    respuesta = client.put(_url(equipo["org"]), json={"tecnologia": ["SAP"]})

    assert respuesta.status_code == 422


def test_el_owner_la_cambia_y_queda_en_la_auditoria(client, equipo, como) -> None:
    familia = _una_familia(equipo["owner"], equipo["org"])
    como(equipo["owner"])

    respuesta = client.put(_url(equipo["org"]), json={"tecnologias": [familia], "cpvs": ["72"]})

    assert respuesta.status_code == 200
    assert respuesta.json()["tecnologias"] == [familia]
    como(equipo["member"])
    leida = client.get(_url(equipo["org"])).json()
    assert (leida["tecnologias"], leida["cpvs"]) == ([familia], ["72"])

    with connect_read() as c:
        detalles = [
            str(f[0])
            for f in c.execute(
                "SELECT detail FROM audit_log WHERE detail LIKE %s",
                (f"event={ORG_SETTINGS_UPDATED} |%",),
            ).fetchall()
        ]
    assert len(detalles) == 1
    assert f"resource=org:{equipo['org']}" in detalles[0]
