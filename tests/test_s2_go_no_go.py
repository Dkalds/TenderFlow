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


def test_una_familia_sin_hechos_no_cuenta_como_requisito_extraido() -> None:
    """El aviso de familia vacía es un ítem, pero no un requisito del pliego."""
    checklist = evaluate(
        licitacion_id="EXP-5",
        organization_id=3,
        record=_record({}),
        capabilities=OrganizationCapabilities(),
        hoy=date(2026, 9, 7),
    )
    assert all(familia.sin_hechos for familia in checklist.familias)
    assert checklist.requisitos_extraidos == 0
    assert checklist.desconocido_extraidos == 0
    # Los conteos de siempre conservan su significado: un aviso por familia.
    assert checklist.total_requisitos == len(checklist.familias)
    assert checklist.desconocido == len(checklist.familias)


def test_los_extraidos_cuentan_solo_las_familias_con_hechos() -> None:
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
        licitacion_id="EXP-6",
        organization_id=3,
        record=_record(facts),
        capabilities=OrganizationCapabilities(),
        hoy=date(2026, 9, 7),
    )
    equipo = next(f for f in checklist.familias if f.familia == "team_requirements")
    assert not equipo.sin_hechos
    assert [f.familia for f in checklist.familias if f.sin_hechos] == [
        "certifications",
        "economic_solvency",
        "technical_solvency",
    ]
    assert checklist.requisitos_extraidos == len(equipo.items) == 2
    assert checklist.desconocido_extraidos == sum(
        1 for item in equipo.items if item.veredicto == "desconocido"
    )


# ── Documentación administrativa (v147) ─────────────────────────────────────


def _requisito_cert(nombre: str) -> dict[str, Any]:
    return {
        "certifications": [
            {
                "name": nombre,
                "scope": "company",
                "description": nombre,
                "confidence": 0.9,
                "evidence": [{"documento_id": 1, "page_number": 3, "quote": nombre}],
            }
        ]
    }


def _certificaciones(*documentos: dict[str, Any]) -> OrganizationCapabilities:
    return OrganizationCapabilities.model_validate({"certificaciones": list(documentos)})


def test_solo_papeleo_administrativo_no_es_haber_declarado_certificaciones() -> None:
    """Quien solo declaró la AEAT no ha dicho nada de su ISO: «desconocido», no
    «no cumple». El checklist no puede castigar a quien rellenó otra familia."""
    checklist = evaluate(
        licitacion_id="EXP-ADM",
        organization_id=3,
        record=_record(_requisito_cert("ISO/IEC 27001")),
        capabilities=_certificaciones(
            {"nombre": "Certificado AEAT", "tipo": "corriente_aeat", "vigente_hasta": "2027-01-31"}
        ),
        hoy=date(2026, 10, 12),
    )
    (item,) = next(f for f in checklist.familias if f.familia == "certifications").items
    assert item.veredicto == "desconocido"


def test_un_documento_administrativo_que_el_pliego_pide_si_cuenta() -> None:
    """Si el pliego pide la clasificación y está declarada, encaja como cualquier otra."""
    checklist = evaluate(
        licitacion_id="EXP-CLAS",
        organization_id=3,
        record=_record(_requisito_cert("Clasificación empresarial grupo V")),
        capabilities=_certificaciones(
            {
                "nombre": "Clasificación empresarial grupo V",
                "tipo": "clasificacion_empresarial",
                "vigente_hasta": "2027-06-30",
            }
        ),
        hoy=date(2026, 10, 12),
    )
    (item,) = next(f for f in checklist.familias if f.familia == "certifications").items
    assert item.veredicto == "cumple"
    assert item.evidencia


# ── Caducidad frente al plazo de presentación ───────────────────────────────


def _iso_que_caduca(vigente_hasta: str) -> OrganizationCapabilities:
    return _certificaciones(
        {
            "nombre": "ISO/IEC 27001",
            "tipo": "certificacion_tecnica",
            "vigente_hasta": vigente_hasta,
        }
    )


def test_una_certificacion_que_caduca_antes_del_plazo_no_cumple() -> None:
    """CU-06 — Vigente hoy, caducada el día que se presenta la oferta: la solvencia se
    acredita a la fecha límite (art. 140.4 LCSP), así que no cubre la oferta, y
    el motivo dice las dos fechas para que se pueda renovar a tiempo."""
    checklist = evaluate(
        licitacion_id="EXP-CAD",
        organization_id=3,
        record=_record(_requisito_cert("ISO/IEC 27001")),
        capabilities=_iso_que_caduca("2026-11-10"),
        hoy=date(2026, 11, 2),
        fecha_presentacion=date(2026, 11, 20),
    )
    certificaciones = next(f for f in checklist.familias if f.familia == "certifications")
    (item,) = certificaciones.items
    assert item.veredicto == "no_cumple"
    assert certificaciones.veredicto == "no_cumple"
    assert "2026-11-10" in item.motivo and "2026-11-20" in item.motivo
    assert item.evidencia


def test_una_certificacion_que_cubre_el_plazo_sigue_cumpliendo() -> None:
    """Vale hasta el día del plazo incluido: ese día todavía está vigente."""
    checklist = evaluate(
        licitacion_id="EXP-CAD",
        organization_id=3,
        record=_record(_requisito_cert("ISO/IEC 27001")),
        capabilities=_iso_que_caduca("2026-11-20"),
        hoy=date(2026, 11, 2),
        fecha_presentacion=date(2026, 11, 20),
    )
    (item,) = next(f for f in checklist.familias if f.familia == "certifications").items
    assert item.veredicto == "cumple"


def test_sin_plazo_conocido_solo_cuenta_la_caducidad_de_hoy() -> None:
    """Sin fecha límite no se inventa una: se juzga como hasta ahora, contra hoy."""
    checklist = evaluate(
        licitacion_id="EXP-CAD",
        organization_id=3,
        record=_record(_requisito_cert("ISO/IEC 27001")),
        capabilities=_iso_que_caduca("2026-11-10"),
        hoy=date(2026, 11, 2),
    )
    (item,) = next(f for f in checklist.familias if f.familia == "certifications").items
    assert item.veredicto == "cumple"


@pytest.mark.parametrize(
    ("valor", "esperada"),
    [
        ("2026-11-15", date(2026, 11, 15)),
        ("2026-11-15T14:00:00", date(2026, 11, 15)),
        (None, None),
        ("", None),
        ("sin fecha", None),
    ],
)
def test_fecha_de_plazo_lee_el_dia_o_nada(valor: object, esperada: date | None) -> None:
    from services.go_no_go import fecha_de_plazo

    assert fecha_de_plazo(valor) == esperada
