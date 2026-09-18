"""S2.3 — ``GET /api/v1/pursuits/{pursuit_id}/checklist``: acceso y ámbito.

``tests/test_s2_checklist_sellado.py`` prueba el sellado llamando a
``build_checklist`` directamente, y ``tests/test_s2_capacidad_permisos.py`` los
permisos de NIFs y del perfil de capacidad. Ninguno pasaba por la ruta del
checklist, y el checklist expone más que el perfil: dice qué requisitos de un
pliego concreto cumple o no una organización concreta, y deja constancia en el
ledger de la oportunidad. Así que aquí se fija quién llega a leerlo.

**El listón es la ruta de detalle.** ``GET /pursuits/{id}`` ya fija el contrato
de una oportunidad ajena: 403 si se nombra una organización a la que no se
pertenece, 404 si la oportunidad no está en la organización resuelta. El
checklist cuelga de la misma oportunidad; si contestara otra cosa, el código de
estado diría a un extraño lo que el detalle le calla. Por eso cada caso de
acceso por HTTP compara las dos rutas además de fijar el código.

**La segunda barrera, sin la ruta delante.** ``build_checklist`` vuelve a
validar la membresía; como la ruta ya la validó antes, eso solo se puede ver
llamando al servicio directamente, y así se prueba.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.routes.dual_auth import require_any_auth
from db.repositories.organization_capabilities import OrganizationCapabilitiesRepository
from db.repositories.organizations import OrganizationRepository
from db.repositories.pursuits import PursuitRepository
from db.repositories.tender_fact_sheets import TenderFactSheetsRepository
from shared.dto import PursuitCreate

_LICITACION = "LIC-CHECKLIST-ACCESO"

_FACTS = {
    "certifications": [
        {
            "name": "ISO/IEC 27001",
            "scope": "company",
            "description": "Seguridad de la información.",
            "confidence": 0.9,
            "evidence": [
                {"documento_id": 1, "page_number": 4, "quote": "Certificación ISO/IEC 27001."}
            ],
        }
    ]
}


class _Sesion:
    """Sustituye ``require_any_auth``: cada test decide quién pide."""

    user_id: int | None = None

    def __call__(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "auth_method": "session",
            "user_key": f"checklist-{self.user_id}",
        }


@pytest.fixture()
def sesion(api_db: Any) -> Iterator[_Sesion]:
    from api.app import app

    principal = _Sesion()
    app.dependency_overrides[require_any_auth] = principal
    try:
        yield principal
    finally:
        app.dependency_overrides.pop(require_any_auth, None)


def _user(email: str) -> int:
    from db.users import create_user

    return create_user(email=email, password_hash="test-hash")  # pragma: allowlist secret


def _oportunidad(owner: int, organization_id: int) -> int:
    from services.pursuits import create_pursuit

    creado, _ = create_pursuit(
        owner, PursuitCreate(licitacion_id=_LICITACION, organization_id=organization_id)
    )
    return int(creado.id)


def _declara_iso(organization_id: int) -> None:
    OrganizationCapabilitiesRepository().replace(
        organization_id,
        certificaciones=[{"nombre": "ISO/IEC 27001", "ambito": "company", "vigente_hasta": None}],
        facturacion=[],
        referencias=[],
        perfiles_equipo=[],
    )


@dataclass(frozen=True)
class _Escenario:
    owner: int
    organizacion: int
    oportunidad: int
    extrano: int
    organizacion_del_extrano: int


@pytest.fixture()
def escenario(sesion: _Sesion) -> _Escenario:
    """Una oportunidad con ficha extraída en una organización que acredita ISO.

    El extraño no es un usuario suelto: es owner de su propia organización,
    que es el caso real —otro cliente del producto— y el que obliga a que el
    ámbito salga de la organización resuelta y no solo de estar autenticado.
    """
    from db.database import connect

    owner = _user("owner-checklist-acceso@example.test")
    extrano = _user("extrano-checklist-acceso@example.test")
    repo = OrganizationRepository()
    organizacion = int(repo.create_organization("Equipo checklist", owner)["id"])
    organizacion_del_extrano = int(repo.create_organization("Otro cliente", extrano)["id"])

    with connect() as conn:
        conn.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, fecha_limite, fecha_extraccion) VALUES (%s, %s, %s, %s)",
            (
                _LICITACION,
                "Servicio de seguridad",
                "2026-12-01T12:00:00+00:00",
                "2026-07-30T10:00:00+00:00",
            ),
        )
    TenderFactSheetsRepository().upsert(
        licitacion_id=_LICITACION,
        status="extracted",
        extraction_version="v3",
        model="modelo-test",
        facts=_FACTS,
        field_count=1,
        evidence_count=1,
    )
    _declara_iso(organizacion)
    oportunidad = _oportunidad(owner, organizacion)
    return _Escenario(owner, organizacion, oportunidad, extrano, organizacion_del_extrano)


def _codigos(client: TestClient, pursuit_id: int, organization_id: int | None) -> tuple[int, int]:
    """``(checklist, detalle)`` para la misma oportunidad y el mismo ámbito."""
    params = {} if organization_id is None else {"organization_id": organization_id}
    checklist = client.get(f"/api/v1/pursuits/{pursuit_id}/checklist", params=params)
    detalle = client.get(f"/api/v1/pursuits/{pursuit_id}", params=params)
    return checklist.status_code, detalle.status_code


def _familia(cuerpo: dict[str, Any], familia: str) -> dict[str, Any]:
    return next(f for f in cuerpo["familias"] if f["familia"] == familia)


def _sellados(organization_id: int, pursuit_id: int) -> list[dict[str, Any]]:
    return [
        evento
        for evento in PursuitRepository().list_events(organization_id, pursuit_id)
        if evento["event_type"] == "checklist_evaluated"
    ]


# ── Quién lo lee ──────────────────────────────────────────────────────────


def test_el_owner_lee_el_checklist_de_su_oportunidad(
    client: TestClient, sesion: _Sesion, escenario: _Escenario
) -> None:
    sesion.user_id = escenario.owner

    respuesta = client.get(
        f"/api/v1/pursuits/{escenario.oportunidad}/checklist",
        params={"organization_id": escenario.organizacion},
    )

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["organization_id"] == escenario.organizacion
    assert cuerpo["licitacion_id"] == _LICITACION
    assert _familia(cuerpo, "certifications")["veredicto"] == "cumple"


@pytest.mark.parametrize("rol", ["admin", "member", "viewer"])
def test_cualquier_miembro_activo_lee_el_checklist(
    client: TestClient, sesion: _Sesion, escenario: _Escenario, rol: str
) -> None:
    """Es una lectura: quien solo mira tiene que entender por qué se propone go o no-go."""
    miembro = _user(f"{rol}-checklist-acceso@example.test")
    OrganizationRepository().add_membership(escenario.organizacion, miembro, rol)
    sesion.user_id = miembro

    assert _codigos(client, escenario.oportunidad, escenario.organizacion) == (200, 200)


# ── Quién no ──────────────────────────────────────────────────────────────


def test_nombrar_una_organizacion_ajena_es_403_como_en_el_detalle(
    client: TestClient, sesion: _Sesion, escenario: _Escenario
) -> None:
    """Lo que fija es el ``(403, 403)``; el ledger se mira solo como guarda.

    Hoy se sella después de validar la membresía y de encontrar la oportunidad.
    Con una sola de las dos barreras caída la otra corta antes de sellar, y con
    las dos caídas del todo el checklist da 200 y falla el ``(403, 403)``. El
    ``[]`` solo falla por su cuenta si coinciden dos fallos: la ruta sin su
    barrera y un servicio que sellara antes de validar. Que el servicio, sin la
    ruta delante, rechace sin dejar rastro lo fija
    ``test_el_servicio_vuelve_a_validar_la_membresia_sin_la_ruta``.
    """
    sesion.user_id = escenario.extrano

    assert _codigos(client, escenario.oportunidad, escenario.organizacion) == (403, 403)
    assert _sellados(escenario.organizacion, escenario.oportunidad) == []


def test_el_servicio_vuelve_a_validar_la_membresia_sin_la_ruta(escenario: _Escenario) -> None:
    """Segunda barrera: ``build_checklist`` rechaza al extraño por sí mismo.

    La ruta resuelve la organización antes de llamarlo y su comentario dice que
    el servicio la vuelve a validar. Con la ruta delante, quitarle esa
    comprobación al servicio no cambia ningún código de estado; llamándolo
    directamente, sí se ve. El ledger se mira después porque un servicio que
    validara después de sellar también lanzaría la excepción, pero con la
    lectura ya sellada en la oportunidad ajena.
    """
    from services.go_no_go import build_checklist
    from services.organizations import OrganizationAccessError

    with pytest.raises(OrganizationAccessError):
        build_checklist(
            escenario.extrano, escenario.oportunidad, organization_id=escenario.organizacion
        )

    assert _sellados(escenario.organizacion, escenario.oportunidad) == []


def test_sin_organization_id_la_oportunidad_ajena_es_404_como_en_el_detalle(
    client: TestClient, sesion: _Sesion, escenario: _Escenario
) -> None:
    """Sin parámetro se resuelve la organización personal, y ahí no existe."""
    sesion.user_id = escenario.extrano

    assert _codigos(client, escenario.oportunidad, None) == (404, 404)


def test_desde_la_organizacion_propia_la_oportunidad_ajena_es_404(
    client: TestClient, sesion: _Sesion, escenario: _Escenario
) -> None:
    """Pertenecer a la organización que se nombra no abre las oportunidades de otra."""
    sesion.user_id = escenario.extrano

    codigos = _codigos(client, escenario.oportunidad, escenario.organizacion_del_extrano)

    assert codigos == (404, 404)


def test_la_organizacion_nombrada_acota_aunque_se_pertenezca_a_las_dos(
    client: TestClient, sesion: _Sesion, escenario: _Escenario
) -> None:
    """Con acceso legítimo a la oportunidad, pedirla desde otra organización es 404.

    Es el caso en que la membresía no ayuda a separar nada: lo único que impide
    contrastar la oportunidad con el perfil equivocado es que la búsqueda se
    haga dentro de la organización resuelta.
    """
    OrganizationRepository().add_membership(
        escenario.organizacion_del_extrano, escenario.owner, "member"
    )
    sesion.user_id = escenario.owner

    assert _codigos(client, escenario.oportunidad, escenario.organizacion_del_extrano) == (
        404,
        404,
    )
    assert _codigos(client, escenario.oportunidad, escenario.organizacion) == (200, 200)


def test_una_oportunidad_inexistente_es_404(
    client: TestClient, sesion: _Sesion, escenario: _Escenario
) -> None:
    sesion.user_id = escenario.owner

    assert _codigos(client, 424242, escenario.organizacion) == (404, 404)


def test_una_membresia_revocada_pierde_el_checklist(
    client: TestClient, sesion: _Sesion, escenario: _Escenario
) -> None:
    antiguo = _user("revocado-checklist-acceso@example.test")
    repo = OrganizationRepository()
    repo.add_membership(escenario.organizacion, antiguo, "member")
    repo.add_membership(escenario.organizacion, antiguo, "member", status="revoked")
    sesion.user_id = antiguo

    assert _codigos(client, escenario.oportunidad, escenario.organizacion) == (403, 403)


# ── Contra qué perfil y qué queda sellado ─────────────────────────────────


def test_se_contrasta_con_el_perfil_de_la_organizacion_de_la_oportunidad(
    client: TestClient, sesion: _Sesion, escenario: _Escenario
) -> None:
    """La misma licitación en dos organizaciones del mismo usuario no comparte veredicto.

    La organización del extraño no declaró certificaciones: si el perfil se
    tomara de otro sitio que la organización resuelta, su checklist heredaría
    el ISO de la otra y diría ``cumple`` por un dato que no es suyo.
    """
    OrganizationRepository().add_membership(
        escenario.organizacion_del_extrano, escenario.owner, "admin"
    )
    oportunidad_ajena = _oportunidad(escenario.owner, escenario.organizacion_del_extrano)
    sesion.user_id = escenario.owner

    con_iso = client.get(
        f"/api/v1/pursuits/{escenario.oportunidad}/checklist",
        params={"organization_id": escenario.organizacion},
    ).json()
    sin_iso = client.get(
        f"/api/v1/pursuits/{oportunidad_ajena}/checklist",
        params={"organization_id": escenario.organizacion_del_extrano},
    ).json()

    assert _familia(con_iso, "certifications")["veredicto"] == "cumple"
    certificaciones = _familia(sin_iso, "certifications")
    assert certificaciones["veredicto"] == "desconocido"
    assert "no ha declarado ninguna certificación" in certificaciones["items"][0]["motivo"]
    assert sin_iso["organization_id"] == escenario.organizacion_del_extrano


def test_el_sellado_registra_quien_leyo_y_el_mismo_recuento_que_la_respuesta(
    client: TestClient, sesion: _Sesion, escenario: _Escenario
) -> None:
    """El evento es la constancia de qué se le propuso a quién: tiene que coincidir.

    ``test_s2_checklist_sellado.py`` cuenta filas; aquí se mira qué dicen. Lee
    un ``viewer`` a propósito: el actor del ledger es quien abrió la pestaña,
    no el owner de la oportunidad.
    """
    viewer = _user("viewer-sellado-acceso@example.test")
    OrganizationRepository().add_membership(escenario.organizacion, viewer, "viewer")
    sesion.user_id = viewer

    cuerpo = client.get(
        f"/api/v1/pursuits/{escenario.oportunidad}/checklist",
        params={"organization_id": escenario.organizacion},
    ).json()

    (evento,) = _sellados(escenario.organizacion, escenario.oportunidad)
    assert evento["actor_user_id"] == viewer
    payload = evento["payload"]
    assert payload["licitacion_id"] == _LICITACION
    assert payload["extraction_version"] == cuerpo["extraction_version"] == "v3"
    assert (payload["cumple"], payload["no_cumple"], payload["desconocido"]) == (
        cuerpo["cumple"],
        cuerpo["no_cumple"],
        cuerpo["desconocido"],
    )
    assert payload["familias"] == {f["familia"]: f["veredicto"] for f in cuerpo["familias"]}


def test_un_fallo_al_sellar_no_tumba_la_lectura(
    client: TestClient,
    sesion: _Sesion,
    escenario: _Escenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El ledger es constancia, no requisito: sin él el checklist se sigue viendo."""
    import services.go_no_go as go_no_go

    def _ledger_caido(**_: Any) -> bool:
        raise RuntimeError("ledger no disponible")

    monkeypatch.setattr(go_no_go, "seal_checklist_evaluated", _ledger_caido)
    sesion.user_id = escenario.owner

    respuesta = client.get(
        f"/api/v1/pursuits/{escenario.oportunidad}/checklist",
        params={"organization_id": escenario.organizacion},
    )

    assert respuesta.status_code == 200
    assert _familia(respuesta.json(), "certifications")["veredicto"] == "cumple"
