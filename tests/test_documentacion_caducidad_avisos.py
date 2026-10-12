"""El productor de avisos de caducidad, contra Postgres.

``services.documentacion_caducidad.emitir_avisos_de_caducidad`` barre los
documentos del perfil de capacidad de todas las organizaciones y escribe en el
outbox un ``organizacion.documento_caduca`` por documento y umbral. Lo que se
fija aquí:

- solo owner y admin activos lo reciben (quienes pueden renovarlo);
- una vez por umbral y documento, aunque el paso corra cada día;
- renovar con otra fecha vuelve a avisar en sus umbrales;
- el despachador lo deja en la campana con el texto del aviso.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

HOY = datetime.now(UTC).date()


def _en(dias: int) -> date:
    return HOY + timedelta(days=dias)


@pytest.fixture()
def equipo(tmp_db) -> dict[str, int]:
    from db.repositories.organizations import OrganizationRepository
    from db.users import create_user

    repo = OrganizationRepository()
    ids = {
        rol: create_user(
            email=f"doc-{rol}@example.test", password_hash="x"
        )  # pragma: allowlist secret
        for rol in ("owner", "admin", "member", "ex_admin")
    }
    org = int(repo.create_organization("Integradora", ids["owner"])["id"])
    repo.add_membership(org, ids["admin"], "admin")
    repo.add_membership(org, ids["member"], "member")
    repo.add_membership(org, ids["ex_admin"], "admin", status="revoked")
    return {"org": org, **ids}


def _declarar(org: int, *documentos: dict) -> None:
    from db.repositories.organization_capabilities import OrganizationCapabilitiesRepository

    OrganizationCapabilitiesRepository().replace(
        org,
        certificaciones=list(documentos),
        facturacion=[],
        referencias=[],
        perfiles_equipo=[],
    )


def _eventos() -> list[dict]:
    from db.events import get_events_by_type

    return get_events_by_type("organizacion.documento_caduca")


def test_avisa_a_quien_puede_renovar_una_vez_por_umbral(equipo):
    from services.documentacion_caducidad import emitir_avisos_de_caducidad

    _declarar(
        equipo["org"],
        {"nombre": "Certificado AEAT", "tipo": "corriente_aeat", "vigente_hasta": _en(20)},
        {"nombre": "ISO 9001", "vigente_hasta": _en(200)},
        {
            "nombre": "Seguridad Social",
            "tipo": "corriente_seguridad_social",
            "vigente_hasta": _en(-2),
        },
        {"nombre": "ROLECE", "tipo": "rolece", "vigente_hasta": None},
    )

    assert emitir_avisos_de_caducidad(HOY) == 2

    por_documento = {e["payload"]["documento"]: e for e in _eventos()}
    assert set(por_documento) == {"Certificado AEAT", "Seguridad Social"}
    aeat = por_documento["Certificado AEAT"]["payload"]
    assert aeat["umbral"] == 30
    assert aeat["dias_restantes"] == 20
    assert aeat["tipo"] == "corriente_aeat"
    assert aeat["categoria"] == "administrativa"
    assert aeat["aviso_titulo"] == "Caduca en 20 días"
    assert {s["user_id"] for s in aeat["seguidores"]} == {equipo["owner"], equipo["admin"]}
    assert por_documento["Seguridad Social"]["payload"]["umbral"] == 0
    assert por_documento["Seguridad Social"]["payload"]["aviso_titulo"] == "Ha caducado"

    # Cada día corre otra vez; nada nuevo que decir.
    assert emitir_avisos_de_caducidad(HOY) == 0
    # Guardar el perfil otra vez (las filas cambian de id) tampoco repite.
    _declarar(
        equipo["org"],
        {"nombre": "certificado  aeat", "tipo": "corriente_aeat", "vigente_hasta": _en(20)},
        {
            "nombre": "Seguridad Social",
            "tipo": "corriente_seguridad_social",
            "vigente_hasta": _en(-2),
        },
    )
    assert emitir_avisos_de_caducidad(HOY) == 0

    # Trece días después, a siete de caducar: el umbral siguiente.
    assert emitir_avisos_de_caducidad(HOY + timedelta(days=13)) == 1
    assert _eventos()[-1]["payload"]["umbral"] == 7


def test_renovar_con_otra_fecha_vuelve_a_avisar(equipo):
    from services.documentacion_caducidad import emitir_avisos_de_caducidad

    _declarar(equipo["org"], {"nombre": "ENS", "vigente_hasta": _en(5)})
    assert emitir_avisos_de_caducidad(HOY) == 1

    # Renovado un año: fuera del horizonte, nada que avisar.
    _declarar(equipo["org"], {"nombre": "ENS", "vigente_hasta": _en(365)})
    assert emitir_avisos_de_caducidad(HOY) == 0
    # Renovado a cincuenta días: otra vigencia, avisa de sus 60 días.
    _declarar(equipo["org"], {"nombre": "ENS", "vigente_hasta": _en(50)})
    assert emitir_avisos_de_caducidad(HOY) == 1
    assert [e["payload"]["umbral"] for e in _eventos()] == [7, 60]


def test_la_organizacion_personal_no_avisa(tmp_db):
    """No concurre a nada y la pantalla no deja declararle perfil."""
    from db.repositories.organizations import OrganizationRepository
    from db.users import create_user
    from services.documentacion_caducidad import emitir_avisos_de_caducidad

    uid = create_user(
        email="doc-personal@example.test", password_hash="x"
    )  # pragma: allowlist secret
    personal = int(OrganizationRepository().ensure_personal_organization(uid)["id"])
    _declarar(personal, {"nombre": "ISO 27001", "vigente_hasta": _en(3)})

    assert emitir_avisos_de_caducidad(HOY) == 0


def test_el_despachador_lo_deja_en_la_campana_de_owner_y_admin(equipo):
    from db.notifications import listar_alertas
    from db.users import get_user_by_id
    from scheduler.jobs.event_dispatch import dispatch_pending
    from services.documentacion_caducidad import emitir_avisos_de_caducidad
    from shared.identity import user_key_from_email

    _declarar(
        equipo["org"],
        {
            "nombre": "Clasificación V-2",
            "tipo": "clasificacion_empresarial",
            "vigente_hasta": _en(45),
        },
    )
    assert emitir_avisos_de_caducidad(HOY) == 1
    dispatch_pending()

    def _bandeja(rol: str) -> list[dict]:
        uid = equipo[rol]
        clave = user_key_from_email(get_user_by_id(uid)["email"], uid)
        return listar_alertas(clave, equipo["org"], user_id=uid, limit=10, offset=0)["items"]

    (aviso,) = _bandeja("owner")
    assert aviso["type"].startswith("documentacion_caduca:")
    assert aviso["title"] == "Caduca en 45 días: Clasificación V-2"
    assert _en(45).isoformat() in aviso["body"]
    assert aviso["licitacion_id"] is None
    assert len(_bandeja("admin")) == 1
    assert _bandeja("member") == []
    assert _bandeja("ex_admin") == []
