"""El resumen diario como producto (B3 del plan 2026-10).

Por licitación: fecha límite, importe base sin IVA o «base desconocida»
(ADR-032), hasta tres requisitos de solvencia de la ficha y el veredicto del
checklist frente a la capacidad, con enlace a la ficha. Sin base de datos: el
formato es puro (``services/email_digest.py``) y el cálculo del pliego reusa
``services.go_no_go.evaluate``, también puro; la carga se sustituye por dobles.

El golden ``tests/fixtures/golden_resumen_diario.txt`` es el texto plano entero
de un correo con una licitación con ficha y base conocida, otra sin ficha y
con base desconocida, y una con solo el total con IVA. Si un cambio lo mueve,
el diff enseña exactamente qué línea del correo cambió.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from services import digest_pliego
from services.email_digest import (
    BloqueDigest,
    PliegoDigest,
    importe_base,
    lineas_de_pliego,
    render_digest,
    visibles_por_bloque,
)
from services.go_no_go import evaluate
from shared.dto import OrganizationCapabilities
from shared.tender_facts import TenderFactSheet, TenderFactSheetRecord

_GOLDEN = Path(__file__).parent / "fixtures" / "golden_resumen_diario.txt"

_CITA = [{"documento_id": 11, "page_number": 13, "quote": "Volumen anual igual o superior."}]

_FACTS: dict[str, Any] = {
    "economic_solvency": [
        {
            "description": "Volumen anual de negocios en el mejor de los tres últimos ejercicios.",
            "amount_eur": 300_000,
            "confidence": 0.9,
            "evidence": _CITA,
        }
    ],
    "technical_solvency": [
        {
            "description": "Contratos similares por importe igual o superior a 200.000 EUR.",
            "confidence": 0.9,
            "evidence": _CITA,
        },
        {
            "description": "Certificado de buena ejecución de al menos dos servicios SAP.",
            "confidence": 0.9,
            "evidence": _CITA,
        },
        {
            "description": "Cuarto requisito que ya no cabe en el correo.",
            "confidence": 0.9,
            "evidence": _CITA,
        },
    ],
}

_CAPACIDAD = OrganizationCapabilities.model_validate(
    {"facturacion": [{"ejercicio": 2025, "importe_eur": 5_000_000}]}
)


def _record(facts: dict[str, Any] | None = None) -> TenderFactSheetRecord:
    return TenderFactSheetRecord(
        licitacion_id="EXP-1",
        status="extracted",
        extraction_version="v3",
        facts=TenderFactSheet.model_validate(facts if facts is not None else _FACTS),
        updated_at="2026-10-01T00:00:00+00:00",
    )


def _checklist(capacidad: OrganizationCapabilities, record: TenderFactSheetRecord | None) -> Any:
    return evaluate(
        licitacion_id="EXP-1",
        organization_id=7,
        record=record,
        capabilities=capacidad,
        hoy=date(2026, 10, 26),
    )


# ── Importe: nunca mezclar bases ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("lic", "esperado"),
    [
        ({"importe_base_sin_iva": 250_000, "importe_tipo": "sin_iva"}, "250.000 € sin IVA"),
        # La columna de base manda aunque el tipo del importe histórico sea otro.
        ({"importe_base_sin_iva": 250_000, "importe_tipo": "con_iva"}, "250.000 € sin IVA"),
        ({"importe": 120_000, "importe_tipo": "sin_iva"}, "120.000 € sin IVA"),
        (
            {"importe": 302_500, "importe_tipo": "con_iva"},
            "base desconocida (302.500 € con IVA)",
        ),
        (
            {"importe": 1, "importe_con_iva": 363_000, "importe_tipo": "con_iva"},
            "base desconocida (363.000 € con IVA)",
        ),
        ({"importe": 250_000, "importe_tipo": "desconocido"}, "base desconocida"),
        ({"importe": 250_000, "importe_tipo": None}, "base desconocida"),
        ({"importe": 250_000}, "base desconocida"),
        ({"importe": 0, "importe_tipo": "sin_iva"}, "base desconocida"),
        ({}, "base desconocida"),
    ],
)
def test_importe_base_sin_iva_o_base_desconocida(lic: dict[str, Any], esperado: str) -> None:
    assert importe_base(lic) == esperado


# ── Pliego: requisitos y checklist ─────────────────────────────────────────


def test_con_ficha_y_capacidad_tres_requisitos_y_veredicto() -> None:
    pliego = digest_pliego.resumen_de_checklist(
        _checklist(_CAPACIDAD, _record()), con_capacidad=True
    )
    assert pliego is not None
    assert [r["familia"] for r in pliego["requisitos"]] == [
        "Solvencia económica",
        "Solvencia técnica",
        "Solvencia técnica",
    ]
    assert pliego["requisitos"][0]["veredicto"] == "cumple"
    checklist = pliego["checklist"]
    assert checklist is not None
    # Cuatro requisitos extraídos: la facturación cumple, la técnica no se puede
    # afirmar sin referencias declaradas.
    assert checklist["cumple"] + checklist["no_cumple"] + checklist["desconocido"] == 4
    assert checklist["cumple"] == 1
    assert checklist["veredicto"] == "desconocido"


def test_sin_capacidad_los_requisitos_sin_veredicto() -> None:
    capacidad = OrganizationCapabilities()
    assert not digest_pliego.capacidad_declarada(capacidad)
    pliego = digest_pliego.resumen_de_checklist(
        _checklist(capacidad, _record()), con_capacidad=False
    )
    assert pliego is not None
    assert all(r["veredicto"] is None for r in pliego["requisitos"])
    assert pliego["checklist"] is None


def test_sin_ficha_nada() -> None:
    assert (
        digest_pliego.resumen_de_checklist(_checklist(_CAPACIDAD, None), con_capacidad=True) is None
    )


def test_ficha_sin_solvencia_solo_el_checklist() -> None:
    facts = {
        "team_requirements": [
            {
                "description": "Jefe de proyecto con cinco años.",
                "role": "Jefe de proyecto",
                "minimum_years": 5,
                "quantity": 1,
                "confidence": 0.9,
                "evidence": _CITA,
            }
        ]
    }
    pliego = digest_pliego.resumen_de_checklist(
        _checklist(_CAPACIDAD, _record(facts)), con_capacidad=True
    )
    assert pliego is not None
    assert pliego["requisitos"] == []
    assert pliego["checklist"] is not None


def test_lineas_de_pliego_recorta_y_nombra_el_veredicto() -> None:
    pliego = PliegoDigest(
        requisitos=[
            {"familia": "Solvencia técnica", "texto": "x" * 300, "veredicto": "no_cumple"},
        ],
        checklist={"veredicto": "no_cumple", "cumple": 1, "no_cumple": 1, "desconocido": 0},
    )
    lineas = lineas_de_pliego(pliego)
    assert lineas[0] == "Solvencia que pide el pliego:"
    assert lineas[1].endswith("… (no cumple)")
    assert len(lineas[1]) < 200
    assert "no cumple (1 cumple · 1 no cumple · 0 sin dato)" in lineas[2]
    assert lineas_de_pliego(None) == []


# ── Tamaño acotado ────────────────────────────────────────────────────────


def test_el_correo_tiene_techo_por_bloque_y_en_total() -> None:
    bloques = [
        BloqueDigest(etiqueta=f"R{i}", licitaciones=[{"id_externo": f"{i}-{j}"} for j in range(12)])
        for i in range(5)
    ]
    assert visibles_por_bloque(bloques) == [10, 10, 10, 0, 0]
    texto, html = render_digest(bloques=bloques, frecuencia="daily", base_url=None, baja_url=None)
    assert texto.count("\n* ") == 30
    assert "… y 12 más." in texto
    assert html.count("border-radius:8px") == 30


# ── Plantilla: con ficha y sin ficha, base conocida y desconocida ──────────


def _bloques_golden() -> list[BloqueDigest]:
    pliego = digest_pliego.resumen_de_checklist(
        _checklist(_CAPACIDAD, _record()), con_capacidad=True
    )
    return [
        BloqueDigest(
            etiqueta="Alerta por defecto · SAP",
            organization_id=7,
            licitaciones=[
                {
                    "id_externo": "EXP-1",
                    "titulo": "Soporte SAP S/4HANA",
                    "organo_contratacion": "Consejería de Hacienda",
                    "importe": 250_000.0,
                    "importe_tipo": "sin_iva",
                    "importe_base_sin_iva": 250_000.0,
                    "fecha_limite": "2026-11-20T14:00:00+00:00",
                    "ccaa": "Madrid",
                    "tecnologia": "SAP",
                    "pliego": pliego,
                },
                {
                    "id_externo": "EXP-2",
                    "titulo": "Mantenimiento SAP BW",
                    "organo_contratacion": "Ayuntamiento de Prueba",
                    "importe": 90_000.0,
                    "importe_tipo": "desconocido",
                    "fecha_limite": "2026-11-05",
                    "tecnologia": "SAP",
                },
                {
                    "id_externo": "EXP-3",
                    "titulo": "Licencias SAP",
                    "organo_contratacion": "Diputación de Prueba",
                    "importe": 60_500.0,
                    "importe_tipo": "con_iva",
                    "importe_con_iva": 60_500.0,
                    "fecha_limite": None,
                },
            ],
        )
    ]


def test_golden_del_texto_plano() -> None:
    texto, _ = render_digest(
        bloques=_bloques_golden(),
        frecuencia="daily",
        base_url="https://app.example",
        baja_url="https://app.example/api/v1/watchlist/rules/baja?k=abc&t=kid.sig",
    )
    assert texto == _GOLDEN.read_text(encoding="utf-8")


def test_plantilla_html_con_y_sin_ficha() -> None:
    _, html = render_digest(
        bloques=_bloques_golden(),
        frecuencia="daily",
        base_url="https://app.example",
        baja_url=None,
    )
    assert "250.000 € sin IVA" in html
    assert "base desconocida" in html
    assert "base desconocida (60.500 € con IVA)" in html
    assert html.count("Solvencia que pide el pliego:") == 1
    assert html.count("Checklist frente a la capacidad de tu organización") == 1
    assert html.count("Abrir la ficha") == 3
    assert 'href="https://app.example/detalle?lic=EXP-1"' in html
    # El importe sin base nunca sale como cifra pelada.
    assert "90.000 €" not in html


# ── Carga en lote: solo lo visible, y los avisos intactos ──────────────────


def test_con_pliegos_carga_solo_lo_visible_y_no_toca_avisos() -> None:
    reglas = BloqueDigest(
        etiqueta="SAP",
        organization_id=7,
        licitaciones=[{"id_externo": f"L-{i}"} for i in range(12)],
    )
    aviso = BloqueDigest(
        etiqueta="Plazo ampliado", es_aviso=True, licitaciones=[{"id_externo": "A"}]
    )
    ficha = {**_record().model_dump(mode="json"), "licitacion_id": "L-0"}
    with (
        patch.object(
            digest_pliego.TenderFactSheetsRepository, "get_many", return_value={"L-0": ficha}
        ) as fichas,
        patch.object(digest_pliego.CondicionesOficialesRepository, "solvencia_de", return_value={}),
        patch.object(
            digest_pliego.OrganizationCapabilitiesRepository,
            "get",
            return_value=_CAPACIDAD.model_dump(mode="json"),
        ) as capacidad,
    ):
        salida = digest_pliego.con_pliegos([reglas, aviso], hoy=date(2026, 10, 26))

    (ids,) = fichas.call_args.args
    assert ids == sorted(f"L-{i}" for i in range(10))
    capacidad.assert_called_once_with(7)
    assert salida[1] is aviso
    con_ficha, sin_ficha = salida[0].licitaciones[0], salida[0].licitaciones[1]
    assert con_ficha["pliego"]["checklist"] is not None
    assert "pliego" not in sin_ficha
    assert len(salida[0].licitaciones) == 12


def test_con_pliegos_con_oficiales_de_placsp() -> None:
    """La solvencia publicada en CODICE llega sin ficha LLM y también se cuenta."""
    solvencia = {
        "L-0": [
            {
                "lote_numero": None,
                "orden": 1,
                "clase": "economica",
                "tipo_codigo": "1",
                "descripcion": "Volumen anual de negocios",
                "umbral_importe": 480_000.0,
                "moneda": "EUR",
                "fecha_extraccion": "2026-10-20",
            }
        ]
    }
    bloque = BloqueDigest(etiqueta="SAP", organization_id=7, licitaciones=[{"id_externo": "L-0"}])
    with (
        patch.object(digest_pliego.TenderFactSheetsRepository, "get_many", return_value={}),
        patch.object(
            digest_pliego.CondicionesOficialesRepository, "solvencia_de", return_value=solvencia
        ),
        patch.object(
            digest_pliego.OrganizationCapabilitiesRepository,
            "get",
            return_value=_CAPACIDAD.model_dump(mode="json"),
        ),
    ):
        (salida,) = digest_pliego.con_pliegos([bloque], hoy=date(2026, 10, 26))
    pliego = salida.licitaciones[0]["pliego"]
    (requisito,) = pliego["requisitos"]
    assert requisito["texto"] == "Volumen anual de negocios"
    assert requisito["veredicto"] == "cumple"
