"""S2.4 — la afinidad deja de ser neutral cuando la organización sí tiene perfil."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest

import services.analytics.scoring as sc_mod
from services.analytics import affinity
from services.analytics.affinity import (
    AffinityPortfolio,
    build_portfolio_from_capabilities,
    resolve_portfolio,
    score_affinity_batch,
)
from services.analytics.scoring_signals import (
    CompetenciaStats,
    ImportePercentiles,
    MargenStats,
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


# ---------------------------------------------------------------------------
# El criterio de aceptación de S2.4, medido donde de verdad se puntúa.
#
# Los tests de arriba fijan el motor; estos fijan que el motor está enchufado.
# `resolve_portfolio` existía desde el PR #274 y nadie lo llamaba: el scorer
# seguía construyendo el portfolio sólo con el perfil personal, así que en
# producción el usuario sin perfil seguía viendo la afinidad neutral por mucha
# referencia que su organización tuviera declarada.
# ---------------------------------------------------------------------------

#: Dos licitaciones con la forma que devuelve la proyección de
#: ``AggregateRepository``: una del terreno de la organización y otra que no.
_FILAS_RADAR: list[dict[str, Any]] = [
    {
        "id_externo": "EXP-A",
        "titulo": "Mantenimiento de SAP para el ayuntamiento",
        "descripcion": "Servicios de soporte",
        "organo_contratacion": "Ayuntamiento de Zaragoza",
        "importe": 400000.0,
        "cpv": "72000000",
        "fecha_limite": "2099-04-15T00:00:00+00:00",
        "estado": "PUB",
        "ccaa": "Aragón",
        "tecnologia": "SAP",
        "fecha_publicacion": "2026-03-01T00:00:00+00:00",
    },
    {
        "id_externo": "EXP-B",
        "titulo": "Suministro de mobiliario escolar",
        "descripcion": "Mesas y sillas",
        "organo_contratacion": "Ayuntamiento de Zaragoza",
        "importe": 120000.0,
        "cpv": "39160000",
        "fecha_limite": "2099-04-15T00:00:00+00:00",
        "estado": "PUB",
        "ccaa": "Aragón",
        "tecnologia": None,
        "fecha_publicacion": "2026-03-01T00:00:00+00:00",
    },
]


@contextmanager
def _radar_sin_bd(monkeypatch: pytest.MonkeyPatch, *, capacidad: AffinityPortfolio | None):
    """Aísla ``get_scoring`` de Postgres y del motor de embeddings.

    Se puntúa en modo page-aligned (``ids``) a propósito: es el único camino
    que no resuelve el ámbito de mercado de la organización, que sería una
    lectura de BD ajena a lo que aquí se mide. Y se fuerza el fallback
    determinista porque lo que se comprueba es que la señal llega y discrimina,
    no que el modelo semántico funcione.
    """
    monkeypatch.setattr(
        affinity,
        "build_organization_portfolio",
        lambda organization_id: capacidad if capacidad is not None else AffinityPortfolio(),
    )
    with ExitStack() as stack:
        stack.enter_context(
            patch.object(sc_mod._repo, "licitaciones_by_ids", return_value=_FILAS_RADAR)
        )
        stack.enter_context(patch.object(sc_mod._repo, "tech_signal_by_ids", return_value={}))
        stack.enter_context(
            patch.object(
                sc_mod,
                "load_importe_percentiles",
                return_value=ImportePercentiles(p10=100000.0, p90=500000.0, fuente="universo_vivo"),
            )
        )
        stack.enter_context(
            patch.object(sc_mod, "load_competencia_stats", return_value=CompetenciaStats())
        )
        stack.enter_context(patch.object(sc_mod, "load_margen_stats", return_value=MargenStats()))
        stack.enter_context(patch("services.embeddings.embeddings_available", return_value=False))
        yield


def _puntuar(organization_id: int | None) -> sc_mod.ScoringResult:
    return sc_mod.get_scoring(
        sc_mod.ScoringFilters(ids=["EXP-A", "EXP-B"]),
        user_key=None,
        organization_id=organization_id,
    )


def test_el_scorer_puntua_con_la_capacidad_de_la_organizacion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Criterio 2 de S2.4: organización con referencias, usuario sin perfil."""
    with _radar_sin_bd(monkeypatch, capacidad=build_portfolio_from_capabilities(_CAPACIDAD)):
        resultado = _puntuar(organization_id=9)

    por_id = {o.id_externo: o for o in resultado.opportunities}
    # No neutral: la dimensión existe, aporta puntos en la fila del terreno de
    # la organización y no en la otra. Sin portfolio la clave ni siquiera se
    # emite —el peso se redistribuye—, que es exactamente el estado que este
    # test tiene que impedir que vuelva.
    assert por_id["EXP-A"].desglose["afinidad"] > 0.0
    assert por_id["EXP-B"].desglose["afinidad"] == 0.0
    assert por_id["EXP-A"].score > por_id["EXP-B"].score

    assert resultado.signals is not None
    assert resultado.signals.afinidad_origen == "organizacion"
    assert resultado.signals.afinidad_metodo == "keyword_cpv_fallback"


def test_sin_organizacion_el_scorer_no_inventa_afinidad(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El comportamiento anterior se conserva: sin señal declarada, sin dimensión."""
    with _radar_sin_bd(monkeypatch, capacidad=None):
        resultado = _puntuar(organization_id=None)

    for oportunidad in resultado.opportunities:
        assert "afinidad" not in oportunidad.desglose
    assert resultado.signals is not None
    assert resultado.signals.afinidad_origen == "ninguno"


def test_afinidad_origen_no_marca_el_score_como_degradado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`afinidad_origen` es aditivo: describe, no denuncia.

    ``degradado`` gobierna el aviso del Radar. Si `ninguno` contase como
    avería, cualquier instalación sin perfiles ni capacidad enseñaría un aviso
    permanente por algo que no está roto.
    """
    salud = sc_mod.ScoringSignalsHealth(
        competencia="ok",
        margen="ok",
        percentiles_fuente="universo_vivo",
        afinidad_metodo="unavailable",
        afinidad_origen="ninguno",
    )
    assert salud.degradado is False
    # Y el campo tiene default, así que un cliente que no lo conoce no rompe.
    sin_campo = sc_mod.ScoringSignalsHealth(
        competencia="ok",
        margen="ok",
        percentiles_fuente="universo_vivo",
        afinidad_metodo="unavailable",
    )
    assert sin_campo.afinidad_origen == "ninguno"


def test_el_perfil_personal_gana_tambien_en_el_scorer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Con perfil personal, la capacidad de la organización ni se lee."""

    def _no_deberia_leerse(organization_id: int) -> AffinityPortfolio:
        raise AssertionError("con perfil personal no se lee el de la organización")

    with _radar_sin_bd(monkeypatch, capacidad=None):
        monkeypatch.setattr(affinity, "build_organization_portfolio", _no_deberia_leerse)
        # `get_scoring` importa el repositorio dentro de la función, así que el
        # parche va sobre el módulo dueño y no sobre el namespace de scoring.
        with patch(
            "db.repositories.user_profiles.get_user_profile",
            return_value={"afinidad_keywords": ["mobiliario"], "cpvs": None},
        ):
            resultado = sc_mod.get_scoring(
                sc_mod.ScoringFilters(ids=["EXP-A", "EXP-B"]),
                user_key="u1",
                organization_id=9,
            )

    por_id = {o.id_externo: o for o in resultado.opportunities}
    assert por_id["EXP-B"].desglose["afinidad"] > 0.0
    assert por_id["EXP-A"].desglose["afinidad"] == 0.0
    assert resultado.signals is not None
    assert resultado.signals.afinidad_origen == "perfil"
