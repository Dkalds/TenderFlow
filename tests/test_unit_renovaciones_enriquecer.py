"""``enriquecer_renovaciones``: la prórroga sale de la ficha y la ficha no sale al contrato."""

from __future__ import annotations

import json

from services.competitive.renovaciones import enriquecer_renovaciones


def test_lee_la_prorroga_de_la_ficha_y_calcula_el_fin_maximo() -> None:
    ficha = json.dumps({"extensions": [{"description": "Prórroga de hasta 12 meses adicionales"}]})
    filas = enriquecer_renovaciones(
        [{"licitacion_id": "L1", "fecha_fin_efectiva": "2026-12-31", "ficha_json": ficha}]
    )
    assert filas[0]["prorroga_meses"] == 12
    assert filas[0]["fecha_fin_con_prorroga"] == "2027-12-31"
    assert "ficha_json" not in filas[0]
    assert filas[0]["fecha_fin_origen"] is None  # la fila no lo traía: se declara


def test_sin_ficha_los_campos_van_a_null_sin_inventar_meses() -> None:
    filas = enriquecer_renovaciones(
        [{"licitacion_id": "L2", "fecha_fin_efectiva": "2026-12-31", "fecha_fin_origen": "real"}]
    )
    assert filas[0]["prorroga_meses"] is None
    assert filas[0]["fecha_fin_con_prorroga"] is None
    assert filas[0]["fecha_fin_origen"] == "real"


def test_no_muta_las_filas_de_entrada() -> None:
    original = {"licitacion_id": "L3", "fecha_fin_efectiva": None, "ficha_json": "{}"}
    enriquecer_renovaciones([original])
    assert "ficha_json" in original
