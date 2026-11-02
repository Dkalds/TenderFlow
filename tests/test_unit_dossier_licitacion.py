"""El dossier de decisión y el historial propio, en sus piezas puras (CU-35).

Lo que va a BD lo recorre ``tests/test_escenario_ficha_decidir.py``; aquí, qué
dice cada bloque del papel según lo que llega, y que el papel se genera.
"""

from __future__ import annotations

from services.competitive.historial_propio import (
    HistorialPropio,
    OportunidadesConOrgano,
    ResumenPropio,
    _oportunidades,
    _resumen,
)
from services.dossier_licitacion import _bloque_checklist, _bloque_expediente, _bloque_historial
from services.ficha_pdf import FichaOportunidad, construir_pdf
from services.go_no_go import ChecklistFamiliaResultado, GoNoGoChecklist


def _checklist(**cambios: object) -> GoNoGoChecklist:
    datos: dict[str, object] = {
        "licitacion_id": "EXP-1",
        "organization_id": 1,
        "ficha_estado": "completed",
        "extraction_version": "tender-facts-v8",
        "ficha_actualizada": "2026-10-30",
        "familias": [
            ChecklistFamiliaResultado(
                familia="certifications",
                etiqueta="Certificaciones",
                veredicto="no_cumple",
                items=[],
            )
        ],
        "total_requisitos": 3,
        "cumple": 1,
        "no_cumple": 1,
        "desconocido": 1,
        "requisitos_extraidos": 3,
        "desconocido_extraidos": 1,
    }
    datos.update(cambios)
    return GoNoGoChecklist.model_validate(datos)


def test_resumen_por_ambito_y_sin_filas_es_cero():
    filas = [
        {
            "ambito": "organo",
            "expedientes": 2,
            "importe": 240000,
            "baja_mediana_pct": 12.345,
            "bajas_n": 2,
        }
    ]

    assert _resumen(filas, "organo") == ResumenPropio(
        expedientes=2, importe=240000.0, baja_mediana_pct=12.3, bajas_n=2
    )
    assert _resumen(filas, "cpv4") == ResumenPropio(expedientes=0, importe=0.0, bajas_n=0)


def test_oportunidades_cuenta_presentadas_ganadas_y_perdidas():
    filas = [
        {"status": "won", "n": 2},
        {"status": "lost", "n": 1},
        {"status": "submitted", "n": 1},
        {"status": "identified", "n": 3},
    ]

    assert _oportunidades(filas) == OportunidadesConOrgano(
        total=7, presentadas=4, ganadas=2, perdidas=1
    )


def test_bloque_checklist_da_veredicto_por_familia_y_no_confunde_sin_dato_con_cumple():
    bloque = _bloque_checklist(_checklist())

    assert ("Certificaciones", "No cumple") in bloque.filas
    assert ("Requisitos", "1 cumple · 1 no cumple · 1 sin dato") in bloque.filas
    assert "«Sin dato» no es «cumple»" in bloque.procedencia
    assert bloque.procedencia.startswith("Ficha del pliego")


def test_bloque_checklist_sin_requisitos_se_omite_con_nota():
    bloque = _bloque_checklist(_checklist(total_requisitos=0, familias=[]))

    assert bloque.vacio
    assert "requisitos" in bloque.nota_vacio


def test_bloque_historial_sin_nif_lo_dice():
    bloque = _bloque_historial(HistorialPropio(licitacion_id="EXP-1", identidad_conocida=False))

    assert bloque.vacio
    assert "NIF" in bloque.nota_vacio


def test_bloque_historial_con_lo_ganado():
    bloque = _bloque_historial(
        HistorialPropio(
            licitacion_id="EXP-1",
            identidad_conocida=True,
            cpv4="7226",
            con_organo=ResumenPropio(
                expedientes=1, importe=200000, baja_mediana_pct=10.0, bajas_n=1
            ),
            en_cpv4=ResumenPropio(expedientes=0, importe=0, bajas_n=0),
        )
    )

    assert bloque.filas[0][0] == "Con este órgano"
    assert bloque.filas[0][1].startswith("1 ganada ·")
    assert ("En el CPV 7226", "Ninguna adjudicación") in bloque.filas


def test_bloque_expediente_declara_la_base_del_importe():
    con_base = _bloque_expediente({"id_externo": "EXP-1", "importe_base_sin_iva": 1000})
    sin_base = _bloque_expediente({"id_externo": "EXP-1", "importe": 1210})

    assert ("Presupuesto base sin IVA", "1,000.00 €") in con_base.filas
    assert ("Importe publicado (base desconocida)", "1,210.00 €") in sin_base.filas


def test_el_dossier_se_genera_como_pdf():
    pdf = construir_pdf(
        FichaOportunidad(
            titulo="Soporte SAP <b>2026",
            subtitulo="Dossier de decisión: ¿nos presentamos?",
            bloques=[
                _bloque_expediente({"id_externo": "EXP-1", "importe": 1000}),
                _bloque_checklist(_checklist()),
                _bloque_historial(None),
            ],
        )
    )

    assert pdf.startswith(b"%PDF")
