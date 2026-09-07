"""S2.3 — contraste ficha × capacidad: golden y reglas que lo sostienen.

El golden (``tests/fixtures/golden_go_no_go.jsonl``) está escrito a mano: fija
el veredicto que un humano espera por familia en diez fichas sintéticas. Si un
cambio de reglas mueve un veredicto, este test lo enseña con el nombre del caso
y la familia, no con un diff de mil líneas.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from services.go_no_go import evaluate
from shared.dto import OrganizationCapabilities
from shared.tender_facts import TenderFactSheet, TenderFactSheetRecord

_GOLDEN = Path(__file__).parent / "fixtures" / "golden_go_no_go.jsonl"


def _casos() -> list[dict[str, Any]]:
    with _GOLDEN.open(encoding="utf-8") as handle:
        return [json.loads(linea) for linea in handle if linea.strip()]


def _record(facts: dict[str, Any]) -> TenderFactSheetRecord:
    return TenderFactSheetRecord(
        licitacion_id="EXP-GOLDEN",
        status="extracted",
        extraction_version="v3",
        facts=TenderFactSheet.model_validate(facts),
        updated_at="2026-09-01T00:00:00+00:00",
    )


def test_golden_tiene_diez_casos_con_las_cuatro_familias() -> None:
    casos = _casos()
    assert len(casos) == 10
    for caso in casos:
        assert set(caso["esperado"]) == {
            "certifications",
            "economic_solvency",
            "technical_solvency",
            "team_requirements",
        }, caso["caso"]


@pytest.mark.parametrize("caso", _casos(), ids=lambda c: str(c["caso"]))
def test_golden_veredicto_por_familia(caso: dict[str, Any]) -> None:
    checklist = evaluate(
        licitacion_id="EXP-GOLDEN",
        organization_id=7,
        record=_record(caso["facts"]),
        capabilities=OrganizationCapabilities.model_validate(caso["capabilities"]),
        hoy=date.fromisoformat(caso["hoy"]),
    )
    obtenido = {familia.familia: familia.veredicto for familia in checklist.familias}
    assert obtenido == caso["esperado"], caso.get("nota", "")


@pytest.mark.parametrize("caso", _casos(), ids=lambda c: str(c["caso"]))
def test_ningun_cumple_sin_evidencia(caso: dict[str, Any]) -> None:
    """La regla 1 del módulo, comprobada sobre los diez casos del golden."""
    checklist = evaluate(
        licitacion_id="EXP-GOLDEN",
        organization_id=7,
        record=_record(caso["facts"]),
        capabilities=OrganizationCapabilities.model_validate(caso["capabilities"]),
        hoy=date.fromisoformat(caso["hoy"]),
    )
    for familia in checklist.familias:
        for item in familia.items:
            if item.veredicto == "cumple":
                assert item.evidencia, f"{caso['caso']}/{item.requisito}"


def test_sin_ficha_las_cuatro_familias_son_desconocido() -> None:
    """Sin ficha no hay hecho que contrastar; la capacidad declarada no basta."""
    checklist = evaluate(
        licitacion_id="EXP-1",
        organization_id=3,
        record=None,
        capabilities=OrganizationCapabilities.model_validate(
            {"facturacion": [{"ejercicio": 2025, "importe_eur": 5_000_000}]}
        ),
        hoy=date(2026, 9, 7),
    )
    assert {f.veredicto for f in checklist.familias} == {"desconocido"}
    assert checklist.ficha_estado is None
    assert checklist.extraction_version is None


def test_el_checklist_declara_version_y_fecha_de_la_ficha() -> None:
    """Un veredicto sin decir sobre qué ficha se calculó no se puede auditar."""
    checklist = evaluate(
        licitacion_id="EXP-2",
        organization_id=3,
        record=_record({}),
        capabilities=OrganizationCapabilities(),
        hoy=date(2026, 9, 7),
    )
    assert checklist.extraction_version == "v3"
    assert checklist.ficha_actualizada == "2026-09-01T00:00:00+00:00"
    assert checklist.ficha_estado == "extracted"


def test_familia_se_queda_con_el_peor_veredicto() -> None:
    """Un requisito incumplido no se diluye con otro que sí se cumple."""
    facts = {
        "team_requirements": [
            {
                "description": "Jefe de proyecto",
                "role": "Jefe de proyecto",
                "minimum_years": 3,
                "confidence": 0.9,
                "evidence": [{"documento_id": 1, "page_number": 1, "quote": "Jefe de proyecto"}],
            },
            {
                "description": "Arquitecto",
                "role": "Arquitecto",
                "minimum_years": 10,
                "confidence": 0.9,
                "evidence": [{"documento_id": 1, "page_number": 1, "quote": "Arquitecto"}],
            },
        ]
    }
    checklist = evaluate(
        licitacion_id="EXP-3",
        organization_id=3,
        record=_record(facts),
        capabilities=OrganizationCapabilities.model_validate(
            {
                "perfiles_equipo": [
                    {"rol": "Jefe de proyecto", "anios": 9, "cantidad": 1},
                    {"rol": "Arquitecto", "anios": 2, "cantidad": 1},
                ]
            }
        ),
        hoy=date(2026, 9, 7),
    )
    equipo = next(f for f in checklist.familias if f.familia == "team_requirements")
    assert equipo.veredicto == "no_cumple"
    assert {item.veredicto for item in equipo.items} == {"cumple", "no_cumple"}


def test_los_totales_cuadran_con_los_items() -> None:
    checklist = evaluate(
        licitacion_id="EXP-4",
        organization_id=3,
        record=_record({}),
        capabilities=OrganizationCapabilities(),
        hoy=date(2026, 9, 7),
    )
    total = checklist.cumple + checklist.no_cumple + checklist.desconocido
    assert total == checklist.total_requisitos
    assert checklist.total_requisitos == sum(len(f.items) for f in checklist.familias)
