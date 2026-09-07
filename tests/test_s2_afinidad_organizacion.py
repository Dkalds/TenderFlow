"""S2.4 — la afinidad deja de ser neutral cuando la organización sí tiene perfil."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest

from services.analytics import affinity
from services.analytics.affinity import (
    AffinityPortfolio,
    build_portfolio_from_capabilities,
    resolve_portfolio,
    score_affinity_batch,
)
from shared.dto import OrganizationCapabilities

_CAPACIDAD = OrganizationCapabilities.model_validate(
    {
        "referencias": [
            {
                "organo": "Ayuntamiento de Zaragoza",
                "importe_eur": 450000,
                "anio": 2024,
                "tecnologia": "SAP",
                "expediente_id": "EXP-2024-1",
            }
        ]
    }
)

_CANDIDATAS = pd.DataFrame(
    [
        {
            "id_externo": "EXP-A",
            "titulo": "Mantenimiento de SAP para el ayuntamiento",
            "descripcion": "Servicios de soporte",
            "cpv": "72000000",
        },
        {
            "id_externo": "EXP-B",
            "titulo": "Suministro de mobiliario escolar",
            "descripcion": "Mesas y sillas",
            "cpv": "39160000",
        },
    ]
)


def test_organizacion_con_referencias_da_afinidad_no_neutral() -> None:
    """El criterio de aceptación de S2.4, con el fallback determinista.

    Se fuerza el camino sin embeddings a propósito: lo que se comprueba es que
    la señal existe y discrimina, no que el modelo semántico funcione.
    """
    portfolio = build_portfolio_from_capabilities(_CAPACIDAD)
    assert portfolio.available

    with patch("services.embeddings.embeddings_available", return_value=False):
        resultado = score_affinity_batch(_CANDIDATAS, portfolio)

    assert resultado.method == "keyword_cpv_fallback"
    assert resultado.scores["EXP-A"] > 0.0
    assert resultado.scores["EXP-B"] == 0.0


def test_las_familias_declaradas_tambien_entran_en_el_portfolio() -> None:
    """Lo que la organización dice que vende cuenta aunque no tenga referencia."""
    portfolio = build_portfolio_from_capabilities(OrganizationCapabilities(), ["MICROSOFT"])
    assert portfolio.keywords == ("MICROSOFT",)
    assert portfolio.available


def test_una_referencia_viaja_como_keyword_y_como_contrato() -> None:
    portfolio = build_portfolio_from_capabilities(_CAPACIDAD)
    assert portfolio.keywords == ("SAP",)
    assert portfolio.contracts == ("Ayuntamiento de Zaragoza · SAP · EXP-2024-1",)


def test_usuario_sin_perfil_hereda_el_portfolio_de_su_organizacion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        affinity,
        "build_organization_portfolio",
        lambda organization_id: build_portfolio_from_capabilities(_CAPACIDAD),
    )
    resolucion = resolve_portfolio(keywords=[], cpvs=[], organization_id=9, tiene_perfil=False)
    assert resolucion.origen == "organizacion"
    assert resolucion.portfolio.keywords == ("SAP",)


def test_el_perfil_personal_manda_sobre_el_de_la_organizacion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Quien rellenó su perfil dijo a qué se dedica él, no su empresa."""

    def _no_deberia_leerse(organization_id: int) -> AffinityPortfolio:
        raise AssertionError("con perfil personal no se lee el de la organización")

    monkeypatch.setattr(affinity, "build_organization_portfolio", _no_deberia_leerse)
    resolucion = resolve_portfolio(keywords=["ERP"], organization_id=9, tiene_perfil=True)
    assert resolucion.origen == "perfil"
    assert resolucion.portfolio.keywords == ("ERP",)


def test_sin_perfil_ni_capacidad_el_origen_es_ninguno(monkeypatch: pytest.MonkeyPatch) -> None:
    """Las keywords globales de configuración no describen a nadie en concreto."""
    monkeypatch.setattr(
        affinity, "build_organization_portfolio", lambda organization_id: AffinityPortfolio()
    )
    resolucion = resolve_portfolio(keywords=["sap"], organization_id=9, tiene_perfil=False)
    assert resolucion.origen == "ninguno"
    assert resolucion.portfolio.keywords == ("sap",)


def test_si_la_capacidad_no_se_puede_leer_el_radar_no_se_cae(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Una señal caída degrada la afinidad; no tumba la pantalla entera."""

    def _explota(organization_id: int) -> Any:
        raise RuntimeError("Postgres caído")

    monkeypatch.setattr(affinity, "build_organization_portfolio", _explota)
    resolucion = resolve_portfolio(keywords=[], organization_id=9, tiene_perfil=False)
    assert resolucion.origen == "ninguno"
    assert resolucion.portfolio.available is False
