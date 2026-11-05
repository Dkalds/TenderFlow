"""C2.9 de punta a punta: el tope diario LLM por organización se aplica.

``llm.budget`` ya sabía llevar un cubo por organización (lo cubre
``tests/test_c2_cuentas.py``), pero las rutas que gastan leían
``organization_id`` de un principal de ``require_any_auth`` que nunca lo trae:
la clave de organización llegaba siempre ``None`` y el cubo no se alimentaba ni
se comprobaba. Estos tests van por HTTP, con dos personas de la misma
organización, para que el fallo no pueda volver a esconderse en la frontera.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

_PREGUNTA = {"question": "¿Qué licitaciones de SAP hay abiertas?"}


@pytest.fixture()
def equipo(api_db: Any) -> dict[str, Any]:
    """Una organización con owner, miembro y viewer, cada uno con su API key."""
    from db.repositories.organizations import OrganizationRepository
    from tests.claves import clave_de_prueba, dueno_de_prueba

    owner = dueno_de_prueba("owner")
    miembro = dueno_de_prueba("miembro")
    lector = dueno_de_prueba("lector")
    repo = OrganizationRepository()
    org_id = int(repo.create_organization("Equipo C2.9", owner)["id"])
    repo.add_membership(org_id, miembro, "member")
    repo.add_membership(org_id, lector, "viewer")
    scopes = "ask:read,licitaciones:read,licitaciones:write"
    return {
        "org_id": org_id,
        "miembro": clave_de_prueba("miembro", scopes=scopes, user_id=miembro),
        "lector": clave_de_prueba("lector", scopes=scopes, user_id=lector),
    }


def _cliente(clave: str) -> TestClient:
    from api.app import app

    cliente = TestClient(app, raise_server_exceptions=False)
    cliente.headers.update({"X-API-Key": clave})
    return cliente


def _guard_con_la_organizacion_agotada(org_id: int) -> Any:
    from llm.budget import BudgetGuard

    guard = BudgetGuard(
        daily_limit_usd=1000.0,
        monthly_limit_usd=10000.0,
        daily_limit_usd_per_user=1000.0,
        daily_limit_usd_per_org=1.0,
        mode="enforce",
    )
    # Gasto de OTRA persona del equipo: el cubo es de la organización.
    guard.record(2.0, "otra-persona", str(org_id))
    return guard


@pytest.mark.parametrize(
    ("ruta", "cuerpo"),
    [
        ("/api/v1/ask", _PREGUNTA),
        ("/api/v1/licitaciones/EXP-C29/resumen", {}),
    ],
)
def test_el_gasto_de_un_companero_agota_el_tope_de_la_organizacion(
    equipo: dict[str, Any], ruta: str, cuerpo: dict[str, Any]
) -> None:
    guard = _guard_con_la_organizacion_agotada(equipo["org_id"])
    with patch("llm.budget.get_budget_guard", return_value=guard):
        resp = _cliente(equipo["miembro"]).post(
            ruta, params={"organization_id": equipo["org_id"]}, json=cuerpo
        )
    assert resp.status_code == 429, resp.text
    assert "organización" in resp.json()["detail"]


def test_sin_organizacion_explicita_el_cubo_es_el_de_la_personal(
    equipo: dict[str, Any],
) -> None:
    """Omitir ``organization_id`` resuelve la personal: hay cubo, pero es otro."""
    from llm.budget import LLMBudgetExceeded

    guard = MagicMock()
    guard.check.side_effect = LLMBudgetExceeded("daily", 2.0, 1.0, scope="org")
    with patch("llm.budget.get_budget_guard", return_value=guard):
        resp = _cliente(equipo["miembro"]).post("/api/v1/ask", json=_PREGUNTA)
    assert resp.status_code == 429
    _sujeto, organizacion = guard.check.call_args.args
    assert organizacion not in (None, str(equipo["org_id"]))


def test_quien_no_es_del_equipo_no_puede_gastar_a_su_cuenta(equipo: dict[str, Any]) -> None:
    from tests.claves import clave_de_prueba

    ajena = clave_de_prueba("ajena", scopes="ask:read")
    resp = _cliente(ajena).post(
        "/api/v1/ask", params={"organization_id": equipo["org_id"]}, json=_PREGUNTA
    )
    assert resp.status_code == 403


@pytest.mark.parametrize(
    ("ruta", "objetivo"),
    [
        (
            "/api/v1/licitaciones/EXP-C29/ficha-pliego/extract",
            "services.rag.fact_sheet.extract_fact_sheet_on_demand",
        ),
        ("/api/v1/licitaciones/EXP-C29/guion", "api.routes.licitaciones.pliegos.generar_guion"),
    ],
)
def test_las_rutas_de_pliegos_atribuyen_el_gasto_a_la_organizacion(
    equipo: dict[str, Any], ruta: str, objetivo: str
) -> None:
    """Aquí el gasto se apunta dentro del servicio, con la organización del contexto."""
    from llm.budget import _current_org

    vista: list[str | None] = []

    def _captura(*_args: Any, **_kwargs: Any) -> Any:
        vista.append(_current_org.get())
        raise ValueError("sin pliegos")

    with patch(objetivo, side_effect=_captura):
        _cliente(equipo["miembro"]).post(ruta, params={"organization_id": equipo["org_id"]})
    assert vista == [str(equipo["org_id"])]


def test_un_viewer_no_lanza_la_extraccion_sincrona(equipo: dict[str, Any]) -> None:
    """Mismo permiso que ``…/extract-async``: extraer sobrescribe la ficha."""
    with patch("services.rag.fact_sheet.extract_fact_sheet_on_demand") as extraer:
        resp = _cliente(equipo["lector"]).post(
            "/api/v1/licitaciones/EXP-C29/ficha-pliego/extract",
            params={"organization_id": equipo["org_id"]},
        )
    assert resp.status_code == 403
    extraer.assert_not_called()
