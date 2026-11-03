"""Composición de las condiciones oficiales de PLACSP por ámbito (v148).

``construir_condiciones`` es la parte de dominio del endpoint: agrupa las filas
de las tres tablas por ámbito —expediente primero, luego cada lote con su
título— y declara la procedencia. Es pura, así que se prueba sin Postgres.
"""

from __future__ import annotations

from typing import Any

import pytest

from services.condiciones_oficiales import construir_condiciones
from shared.dto import IndicioPliego


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


# ── Indicios ─────────────────────────────────────────────────────────────────


def _solvencia(
    clase: str,
    tipo: str | None,
    descripcion: str,
    umbral: float | None = None,
    lote: str | None = None,
) -> dict[str, Any]:
    return {
        "lote_numero": lote,
        "orden": 1,
        "clase": clase,
        "tipo_codigo": tipo,
        "descripcion": descripcion,
        "umbral_importe": umbral,
        "moneda": "EUR",
        "fecha_extraccion": "2026-10-12T10:00:00Z",
    }


def _indicios(datos: dict[str, Any]) -> list[IndicioPliego]:
    return construir_condiciones("EXP-1", datos).indicios


def test_volumen_de_negocios_por_encima_de_1_5_veces_el_valor_estimado_es_indicio() -> None:
    datos = _datos(
        valor_estimado=200_000.0,
        solvencia=[_solvencia("economica", "5", "Volumen anual de negocios", umbral=600_000.0)],
    )

    (indicio,) = _indicios(datos)

    assert indicio.codigo == "solvencia_economica_excesiva"
    assert indicio.detalle == (
        "Pide 600.000 € de volumen anual de negocios, 3,0 veces el valor estimado del contrato (200.000 €)."
    )
    assert indicio.base_legal.startswith("Art. 87.1.a) LCSP")
    assert indicio.cita == "Volumen anual de negocios"


@pytest.mark.parametrize(
    ("tipo", "umbral", "valor_estimado"),
    [
        pytest.param("5", 300_000.0, 200_000.0, id="justo-en-el-tope"),
        pytest.param("3", 600_000.0, 200_000.0, id="seguro-no-tiene-tope"),
        pytest.param("5", 600_000.0, None, id="sin-valor-estimado"),
    ],
)
def test_volumen_dentro_del_tope_o_sin_base_no_es_indicio(
    tipo: str, umbral: float, valor_estimado: float | None
) -> None:
    datos = _datos(
        valor_estimado=valor_estimado,
        solvencia=[_solvencia("economica", tipo, "Requisito económico", umbral=umbral)],
    )

    assert _indicios(datos) == []


def test_juicio_de_valor_por_encima_de_la_mitad_es_indicio_por_ambito() -> None:
    datos = _datos(
        criterios=[
            _criterio(1, "1", peso_pct=40.0, tipo_codigo="OBJ", es_precio=True),
            _criterio(2, "1", peso_pct=60.0, tipo_codigo="SUBJ"),
            _criterio(3, "1", padre_orden=2, peso_pct=None, tipo_codigo="SUBJ"),
            _criterio(1, "2", peso_pct=50.0, tipo_codigo="OBJ"),
            _criterio(2, "2", peso_pct=50.0, tipo_codigo="SUBJ"),
        ]
    )

    (indicio,) = _indicios(datos)

    assert (indicio.codigo, indicio.lote_numero) == ("juicio_de_valor_mayoritario", "1")
    assert indicio.detalle.startswith(
        "El 60 % de la puntuación depende de un juicio de valor y el 40 %"
    )


def test_juicio_de_valor_sin_escala_deducible_no_es_indicio() -> None:
    datos = _datos(criterios=[_criterio(1, peso_pct=30.0, tipo_codigo="SUBJ")])

    assert _indicios(datos) == []


def test_certificado_sin_equivalentes_es_un_indicio_por_norma_y_ambito() -> None:
    datos = _datos(
        solvencia=[
            _solvencia("tecnica", "XSR-CALIDAD", "- Certificación ISO 9001 y ISO 14001."),
            _solvencia("tecnica", "XSR-CALIDAD", "Certificado UNE-EN ISO 9001 vigente."),
        ]
    )

    assert [(i.codigo, i.titulo) for i in _indicios(datos)] == [
        ("certificado_sin_equivalente", "ISO 9001 sin mencionar equivalentes"),
        ("certificado_sin_equivalente", "ISO 14001 o EMAS sin mencionar equivalentes"),
    ]


@pytest.mark.parametrize(
    "descripcion",
    [
        "Certificación ISO 9001 o equivalente.",
        "Certificat ISO 9001 o equivalent.",
        "ISO 9001 ziurtagiria edo baliokidea.",
        "Certificación ENS de categoría media.",
    ],
)
def test_certificado_que_admite_equivalentes_o_no_es_de_calidad_no_es_indicio(
    descripcion: str,
) -> None:
    datos = _datos(solvencia=[_solvencia("tecnica", "XSR-CALIDAD", descripcion)])

    assert _indicios(datos) == []


def test_construir_condiciones_trae_los_indicios_y_el_valor_estimado() -> None:
    datos = _datos(
        valor_estimado=100_000.0,
        solvencia=[_solvencia("economica", "5", "Volumen", umbral=400_000.0)],
    )

    condiciones = construir_condiciones("EXP-1", datos)

    assert condiciones.valor_estimado == 100_000.0
    assert [i.codigo for i in condiciones.indicios] == ["solvencia_economica_excesiva"]
