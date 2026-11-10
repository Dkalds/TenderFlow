"""Acuerdos marco y sistemas dinámicos en los conectores de TED y PSCP (v178).

Los avisos de TED son respuestas reales de la API de búsqueda, guardadas el
2026-11-10 en ``tests/fixtures/ted/marcos_reales.json``; los valores de PSCP
son los cuatro que la columna ``racionalitzacio_contractacio`` tiene en el
dataset vivo. El parser de PLACSP está en
``tests/test_codice_parser_sistema_contratacion.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scraper.connectors.base import RawNotice
from scraper.connectors.pscp import PscpConnector
from scraper.connectors.ted import _FIELDS, TedConnector, _adjudicatarios, _sistema_y_marco

_AVISOS: dict[str, dict[str, Any]] = {
    aviso["publication-number"]: aviso
    for aviso in json.loads(
        (Path(__file__).parent / "fixtures" / "ted" / "marcos_reales.json").read_text("utf-8")
    )
}


def _parsear(numero: str) -> Any:
    parsed = TedConnector().parse(RawNotice(natural_id=numero, payload=_AVISOS[numero]))
    assert parsed is not None
    return parsed


@pytest.mark.parametrize(
    ("numero", "sistema", "marco_ref"),
    [
        # Convocatoria que establece un acuerdo marco (fa-mix, seis participantes).
        ("686159-2026", "marco", None),
        # Adjudicación del marco: BT-765 sin BT-768.
        ("649072-2024", "marco", None),
        # Contrato basado, con el aviso de su marco como número de publicación.
        ("684052-2026", "basado_marco", "ted:649072-2024"),
        # Contrato basado cuyo marco va como UUID del aviso: basado, sin enlace.
        ("689453-2026", "basado_marco", None),
        # Convocatorias que establecen un sistema dinámico; en la segunda, un lote no lo usa.
        ("724362-2025", "sda", None),
        ("730393-2025", "sda", None),
        # Adjudicaciones con BT-766: no hay campo que diga si son el sistema o un específico.
        ("772754-2025", None, None),
        ("48014-2026", None, None),
    ],
)
def test_avisos_reales(numero: str, sistema: str | None, marco_ref: str | None) -> None:
    lic = _parsear(numero).licitacion

    assert lic.sistema_contratacion == sistema
    assert lic.marco_ref == marco_ref


def test_la_adjudicacion_de_un_marco_guarda_a_todos_sus_admitidos() -> None:
    """Hasta 2026-11-10 solo se guardaba el primero de los diecinueve."""
    parsed = _parsear("649072-2024")

    nombres = [a.nombre for a in parsed.adjudicaciones]
    assert len(nombres) == 19
    assert len(set(nombres)) == len(nombres)
    assert "EVOLUTIO CLOUD ENABLER, SAU" in nombres
    # El importe del aviso es de todos los contratos: no se reparte ni se repite.
    assert {a.importe_adjudicado for a in parsed.adjudicaciones} == {None}


def test_un_solo_adjudicatario_conserva_su_identificador() -> None:
    (adjudicacion,) = _parsear("684052-2026").adjudicaciones

    assert adjudicacion.nombre == "EVOLUTIO CLOUD ENABLER, S.A.U."
    assert adjudicacion.nif == "A80448194"


def test_identificadores_sin_alinear_no_se_cruzan_con_otra_empresa() -> None:
    aviso = {"winner-name": {"spa": ["A SL", "B SA", "A SL"]}, "winner-identifier": ["B1", "A2"]}

    assert _adjudicatarios(aviso) == [("A SL", None), ("B SA", None)]


def test_la_vigencia_del_marco_llega_a_las_columnas_de_renovaciones() -> None:
    marco = _parsear("686159-2026").licitacion
    assert (marco.duracion_valor, marco.duracion_unidad) == (4.0, "ANN")

    sda = _parsear("724362-2025").licitacion
    assert (sda.fecha_inicio, sda.fecha_fin) == ("2025-11-28", "2027-11-29")


def test_la_vigencia_no_se_guarda_fuera_de_un_marco() -> None:
    """Un basado trae duración, pero es la suya: abrirla a todo TED está sin medir."""
    basado = _parsear("684052-2026").licitacion

    assert _AVISOS["684052-2026"]["duration-period-value-lot"] == ["12"]
    assert basado.duracion_valor is None
    assert basado.duracion_unidad is None


@pytest.mark.parametrize(
    ("aviso", "esperado"),
    [
        ({"framework-agreement-lot": ["none"], "dps-usage-lot": ["none"]}, "ninguno"),
        # Sin los campos, la fuente no dice nada: no es «ninguno».
        ({}, None),
        ({"framework-agreement-lot": ["none"]}, None),
        ({"contract-framework-agreement": [True]}, "basado_marco"),
    ],
)
def test_ninguno_solo_si_la_fuente_lo_dice(aviso: dict[str, Any], esperado: str | None) -> None:
    assert _sistema_y_marco(aviso, "cn-standard") == (esperado, None)


def test_el_numero_del_marco_con_ceros_a_la_izquierda_casa_con_su_id() -> None:
    """El XML de eForms lo rellena a ocho cifras; ``id_externo`` no."""
    aviso = {"framework-notice-id": ["00649072-2024"]}

    assert _sistema_y_marco(aviso, "can-standard") == ("basado_marco", "ted:649072-2024")


def test_dos_marcos_distintos_en_un_aviso_no_dan_enlace() -> None:
    aviso = {"framework-notice-id": ["649072-2024", "175163-2024"]}

    assert _sistema_y_marco(aviso, "can-standard") == ("basado_marco", None)


def test_el_conector_pide_los_campos_a_la_api() -> None:
    """Un nombre que la API no conoce devuelve 400 a toda la pasada: son los comprobados."""
    assert {
        "framework-agreement-lot",
        "dps-usage-lot",
        "contract-framework-agreement",
        "framework-notice-id",
        "winner-identifier",
        "duration-period-value-lot",
        "duration-period-unit-lot",
        "contract-duration-start-date-lot",
        "contract-duration-end-date-lot",
    } <= set(_FIELDS)


# ── PSCP ─────────────────────────────────────────────────────────────────────

_FICHA = "https://contractaciopublica.cat/ca/detall-publicacio/6f1c2a3b-0d4e-4f5a-9b8c-7d6e5f4a3b2c/300000001"


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        ("Acord Marc", "marco"),
        ("Sistema Dinàmic d'adquisició", "sda"),
        ("Contracte basat en acord marc", "basado_marco"),
        ("Específic de Sistema Dinàmic d'adquisició", "basado_sda"),
        # Tres de cada cuatro filas no traen la columna: sin dato, no «ninguno».
        (None, None),
        ("Un valor que el dataset no tenía el 2026-11-10", None),
    ],
)
def test_pscp_lee_la_racionalizacion(valor: str | None, esperado: str | None) -> None:
    registro = {
        "codi_expedient": "CTTI-2026-00123",
        "objecte_contracte": "Implantació i suport de SAP S/4HANA al CTTI",
        "codi_cpv": "72000000",
        "fase_publicacio": "Anunci de licitació",
        "enllac_publicacio": {"url": _FICHA},
        "racionalitzacio_contractacio": valor,
    }

    parsed = PscpConnector(dataset_id="test-test").parse(
        RawNotice(natural_id="CTTI-2026-00123", payload=registro)
    )

    assert parsed is not None
    assert parsed.licitacion.sistema_contratacion == esperado
    # El enlace al marco va en el JSON de cada fase, que el conector no lee.
    assert parsed.licitacion.marco_ref is None
