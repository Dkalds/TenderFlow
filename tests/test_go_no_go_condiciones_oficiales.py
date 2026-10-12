"""El checklist Go/No-Go contrasta la solvencia oficial de PLACSP cuando existe (v149).

Las reglas que se añaden a las de S2.3, y que estos tests fijan:

- **Por familia, la fuente oficial manda.** Si la publicación oficial trae
  requisitos de solvencia económica (o técnica), se contrastan esos y no los
  de la ficha LLM de esa familia: mezclarlos contaría dos veces el mismo
  requisito con dos redacciones. La familia sin dato oficial sigue con la ficha.
- **La regla 1 se generaliza, no se relaja.** Un ``cumple`` necesita una fuente
  que alguien pueda ir a comprobar: una cita del pliego o la publicación
  oficial, que es pública y está enlazada. Cada ítem dice cuál (``fuente``).
- **Solo el ámbito de la oportunidad.** Con lote, el expediente y ese lote;
  sin lote, todos, con el lote delante del requisito.
- La clasificación empresarial no entra: el perfil de capacidad no la declara.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from services.go_no_go import evaluate
from shared.dto import (
    CondicionesAmbito,
    CondicionesOficiales,
    OrganizationCapabilities,
    RequisitoSolvenciaOficial,
)
from shared.tender_facts import TenderFactSheet, TenderFactSheetRecord

_CAPACIDAD = OrganizationCapabilities.model_validate(
    {
        "facturacion": [
            {"ejercicio": 2024, "importe_eur": 900_000},
            {"ejercicio": 2025, "importe_eur": 1_200_000},
        ],
        "referencias": [
            {"organo": "SEPE", "anio": 2025, "importe_eur": 350_000, "tecnologia": "SAP"},
        ],
    }
)


def _oficiales(*ambitos: CondicionesAmbito) -> CondicionesOficiales:
    return CondicionesOficiales(
        licitacion_id="EXP-1",
        url_publicacion="https://contrataciondelestado.es/wps/poc?uri=deeplink:detalle_licitacion&idEvl=1",
        actualizado="2026-10-12T10:00:00Z",
        ambitos=list(ambitos),
    )


def _solvencia(clase: str, orden: int = 1, **campos: Any) -> RequisitoSolvenciaOficial:
    return RequisitoSolvenciaOficial.model_validate({"orden": orden, "clase": clase, **campos})


def _ficha(facts: dict[str, Any]) -> TenderFactSheetRecord:
    return TenderFactSheetRecord(
        licitacion_id="EXP-1",
        status="extracted",
        extraction_version="v3",
        facts=TenderFactSheet.model_validate(facts),
        updated_at="2026-09-01T00:00:00+00:00",
    )


def _familia(checklist: Any, nombre: str) -> Any:
    return next(f for f in checklist.familias if f.familia == nombre)


def _evaluar(
    oficiales: CondicionesOficiales | None,
    *,
    record: TenderFactSheetRecord | None = None,
    lote_numero: str | None = None,
) -> Any:
    return evaluate(
        licitacion_id="EXP-1",
        organization_id=3,
        record=record,
        capabilities=_CAPACIDAD,
        hoy=date(2026, 10, 12),
        oficiales=oficiales,
        lote_numero=lote_numero,
    )


def test_solvencia_economica_oficial_con_umbral_cumple_sin_cita_del_pliego() -> None:
    oficiales = _oficiales(
        CondicionesAmbito(
            solvencia=[
                _solvencia(
                    "economica",
                    descripcion="Volumen anual de negocios",
                    umbral_importe=1_000_000,
                    moneda="EUR",
                )
            ]
        )
    )

    checklist = _evaluar(oficiales)

    familia = _familia(checklist, "economic_solvency")
    (item,) = familia.items
    assert familia.fuente == "placsp"
    assert (item.veredicto, item.fuente, item.evidencia) == ("cumple", "placsp", [])
    assert item.requisito == "Volumen anual de negocios"
    assert "1.000.000 €" in item.motivo and "publicación oficial" in item.motivo
    assert checklist.usa_condiciones_oficiales is True
    assert checklist.condiciones_actualizadas == "2026-10-12T10:00:00Z"


def test_umbral_oficial_por_encima_de_la_facturacion_no_cumple() -> None:
    oficiales = _oficiales(
        CondicionesAmbito(solvencia=[_solvencia("economica", umbral_importe=2_000_000)])
    )

    (item,) = _familia(_evaluar(oficiales), "economic_solvency").items

    assert item.veredicto == "no_cumple"
    # Sin descripción, el requisito se nombra por su clase, sin inventar texto.
    assert item.requisito == "Solvencia económica (publicación oficial)"


def test_solvencia_tecnica_oficial_con_importe_en_el_texto() -> None:
    oficiales = _oficiales(
        CondicionesAmbito(
            solvencia=[
                _solvencia(
                    "tecnica",
                    descripcion="Servicios similares por importe igual o superior a 300.000 euros",
                )
            ]
        )
    )

    (item,) = _familia(_evaluar(oficiales), "technical_solvency").items

    assert (item.veredicto, item.fuente) == ("cumple", "placsp")


def test_sin_umbral_oficial_es_desconocido_y_lo_atribuye_a_la_publicacion() -> None:
    oficiales = _oficiales(
        CondicionesAmbito(solvencia=[_solvencia("economica", descripcion="Seguro de RC")])
    )

    (item,) = _familia(_evaluar(oficiales), "economic_solvency").items

    assert item.veredicto == "desconocido"
    assert item.motivo.startswith("La publicación oficial no cifra")


def test_la_familia_con_dato_oficial_ignora_la_ficha_y_la_otra_sigue_con_la_ficha() -> None:
    cita = {"documento_id": 1, "page_number": 3, "quote": "Volumen de negocios de 500.000 euros"}
    ficha = _ficha(
        {
            "economic_solvency": [
                {
                    "description": "Volumen de negocios de 500.000 euros",
                    "amount_eur": 500_000,
                    "confidence": 0.9,
                    "evidence": [cita],
                }
            ],
            "technical_solvency": [
                {
                    "description": "Referencias SAP en los últimos tres años",
                    "confidence": 0.9,
                    "evidence": [{**cita, "quote": "Referencias SAP"}],
                }
            ],
        }
    )
    oficiales = _oficiales(
        CondicionesAmbito(solvencia=[_solvencia("economica", umbral_importe=1_000_000)])
    )

    checklist = _evaluar(oficiales, record=ficha)

    economica = _familia(checklist, "economic_solvency")
    tecnica = _familia(checklist, "technical_solvency")
    assert [i.fuente for i in economica.items] == ["placsp"]
    assert [i.fuente for i in tecnica.items] == ["pliego"]
    assert tecnica.fuente == "pliego"
    assert tecnica.items[0].veredicto == "cumple" and tecnica.items[0].evidencia


def test_con_lote_solo_el_expediente_y_ese_lote() -> None:
    oficiales = _oficiales(
        CondicionesAmbito(solvencia=[_solvencia("economica", descripcion="Común")]),
        CondicionesAmbito(
            lote_numero="1", solvencia=[_solvencia("economica", descripcion="Del lote 1")]
        ),
        CondicionesAmbito(
            lote_numero="2", solvencia=[_solvencia("economica", descripcion="Del lote 2")]
        ),
    )

    con_lote = _familia(_evaluar(oficiales, lote_numero="2"), "economic_solvency")
    sin_lote = _familia(_evaluar(oficiales), "economic_solvency")

    assert [i.requisito for i in con_lote.items] == ["Común", "Del lote 2"]
    assert [i.requisito for i in sin_lote.items] == [
        "Común",
        "Lote 1 · Del lote 1",
        "Lote 2 · Del lote 2",
    ]


def test_sin_ficha_pero_con_dato_oficial_se_contrasta_igual() -> None:
    oficiales = _oficiales(
        CondicionesAmbito(solvencia=[_solvencia("economica", umbral_importe=1_000_000)])
    )

    checklist = _evaluar(oficiales, record=None)

    assert checklist.ficha_estado is None
    assert checklist.requisitos_extraidos == 1
    assert _familia(checklist, "economic_solvency").veredicto == "cumple"
    assert _familia(checklist, "certifications").sin_hechos is True


def test_la_clasificacion_no_entra_en_el_checklist() -> None:
    oficiales = _oficiales(
        CondicionesAmbito(solvencia=[_solvencia("clasificacion", tipo_codigo="V2")])
    )

    checklist = _evaluar(oficiales)

    assert checklist.requisitos_extraidos == 0
    assert checklist.usa_condiciones_oficiales is False


def test_sin_dato_oficial_nada_cambia() -> None:
    checklist = _evaluar(_oficiales())

    assert checklist.usa_condiciones_oficiales is False
    assert checklist.condiciones_actualizadas is None
    assert {f.fuente for f in checklist.familias} == {"pliego"}
