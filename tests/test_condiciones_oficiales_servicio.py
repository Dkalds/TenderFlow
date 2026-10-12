"""Composición de las condiciones oficiales de PLACSP por ámbito (v149).

``construir_condiciones`` es la parte de dominio del endpoint: agrupa las filas
de las tres tablas por ámbito —expediente primero, luego cada lote con su
título— y declara la procedencia. Es pura, así que se prueba sin Postgres.
"""

from __future__ import annotations

from typing import Any

from services.condiciones_oficiales import construir_condiciones


def _datos(**extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "criterios": [],
        "garantias": [],
        "solvencia": [],
        "lotes": {},
        "actualizado": None,
        "existe": True,
        "url": "https://contrataciondelestado.es/wps/poc?uri=deeplink:detalle_licitacion&idEvl=X",
    }
    base.update(extra)
    return base


def _criterio(orden: int, lote: str | None = None, **campos: Any) -> dict[str, Any]:
    return {
        "lote_numero": lote,
        "orden": orden,
        "padre_orden": None,
        "descripcion": f"Criterio {orden}",
        "peso": None,
        "peso_pct": None,
        "es_precio": False,
        "tipo_codigo": None,
        "subtipo_codigo": None,
        "nota": None,
        "fecha_extraccion": "2026-10-12T10:00:00Z",
        **campos,
    }


def test_agrupa_por_ambito_con_el_expediente_primero_y_titulos_de_lote() -> None:
    datos = _datos(
        criterios=[
            _criterio(1, descripcion="Precio", peso=60.0, peso_pct=60.0, es_precio=True),
            _criterio(1, "2", descripcion="Precio lote 2"),
        ],
        garantias=[
            {
                "lote_numero": "1",
                "orden": 1,
                "tipo_codigo": "1",
                "porcentaje": None,
                "importe": 4800.0,
                "moneda": "EUR",
                "descripcion": None,
                "fecha_extraccion": "2026-10-12T10:00:00Z",
            }
        ],
        solvencia=[
            {
                "lote_numero": None,
                "orden": 1,
                "clase": "economica",
                "tipo_codigo": "1",
                "descripcion": "Volumen anual de negocios",
                "umbral_importe": 480000.0,
                "moneda": "EUR",
                "fecha_extraccion": "2026-10-12T10:00:00Z",
            }
        ],
        lotes={"1": "Licencias", "2": "Soporte"},
        actualizado="2026-10-12T10:00:00Z",
    )

    condiciones = construir_condiciones("EXP-1", datos)

    assert condiciones.licitacion_id == "EXP-1"
    assert condiciones.fuente == "placsp"
    assert condiciones.actualizado == "2026-10-12T10:00:00Z"
    assert condiciones.url_publicacion is not None
    assert [(a.lote_numero, a.lote_titulo) for a in condiciones.ambitos] == [
        (None, None),
        ("1", "Licencias"),
        ("2", "Soporte"),
    ]
    expediente, lote_1, lote_2 = condiciones.ambitos
    assert [c.descripcion for c in expediente.criterios] == ["Precio"]
    assert expediente.criterios[0].es_precio is True
    assert [s.umbral_importe for s in expediente.solvencia] == [480000.0]
    assert [g.importe for g in lote_1.garantias] == [4800.0]
    assert lote_1.criterios == [] and lote_2.garantias == []


def test_sin_filas_no_hay_ambitos() -> None:
    condiciones = construir_condiciones("EXP-1", _datos())

    assert condiciones.ambitos == []
    assert condiciones.actualizado is None


def test_un_lote_sin_fila_en_lotes_sale_sin_titulo() -> None:
    condiciones = construir_condiciones("EXP-1", _datos(criterios=[_criterio(1, "7")]))

    assert [(a.lote_numero, a.lote_titulo) for a in condiciones.ambitos] == [("7", None)]
