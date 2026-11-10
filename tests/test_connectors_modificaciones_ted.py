"""Los avisos ``can-modif`` de TED son modificaciones, no licitaciones (v180, CU-38).

Los avisos son respuestas reales de la API de búsqueda, guardadas el
2026-11-10 en ``tests/fixtures/ted/modificaciones_reales.json``: dos
modificaciones encadenadas del Ajuntament de Sabadell (718637-2026 modifica
786-2026, que modifica la adjudicación 871071-2025).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scraper.connectors.base import RawNotice
from scraper.connectors.ted import _FIELDS, TedConnector

_RESPUESTA = json.loads(
    (Path(__file__).parent / "fixtures" / "ted" / "modificaciones_reales.json").read_text("utf-8")
)
_AVISOS: dict[str, dict[str, Any]] = {a["publication-number"]: a for a in _RESPUESTA["notices"]}


def _pendientes(*numeros: str) -> list[Any]:
    conector = TedConnector()
    for numero in numeros:
        assert conector.parse(RawNotice(natural_id=numero, payload=_AVISOS[numero])) is None
    return conector.modificaciones_pendientes()


def test_un_aviso_de_modificacion_no_es_una_licitacion_sino_una_modificacion() -> None:
    [modificacion] = _pendientes("786-2026")

    assert (modificacion.clave, modificacion.fuente) == ("ted:786-2026", "ted")
    assert modificacion.licitacion_id is None
    assert modificacion.fecha_publicacion == "2026-01-02"
    assert modificacion.motivo_codigo == "add-wss"
    assert modificacion.motivo is not None and "387.777,17" in modificacion.motivo
    assert modificacion.descripcion is not None and "licencias" in modificacion.descripcion
    assert modificacion.organo == "Ajuntament de Sabadell"
    assert modificacion.url == "https://ted.europa.eu/es/notice/786-2026/pdf"


def test_bt720_es_el_valor_del_aviso_sin_base_y_no_el_importe_final() -> None:
    [modificacion] = _pendientes("786-2026")

    assert (modificacion.importe_aviso, modificacion.importe_aviso_base) == (
        320477.0,
        "desconocido",
    )
    assert modificacion.importe_final is None
    assert modificacion.importe_modificacion is None


def test_guarda_el_aviso_que_modifica_y_el_suyo_para_enlazar_la_cadena() -> None:
    primera, segunda = _pendientes("786-2026", "718637-2026")

    # BT-1501 en su forma de UUID con versión; el original es la adjudicación 871071-2025.
    assert primera.aviso_original == "cb2be52c-ecc0-4a3d-be12-af16ec0b3b6b-01"
    assert primera.identificador_aviso == "be80e249-3d04-4f02-91f7-761b9ad0ed4f"
    # La segunda cita a la primera, no a la adjudicación.
    assert segunda.aviso_original == f"{primera.identificador_aviso}-01"


def test_el_bufer_se_vacia_al_leerlo() -> None:
    conector = TedConnector()
    conector.parse(RawNotice(natural_id="786-2026", payload=_AVISOS["786-2026"]))

    assert len(conector.modificaciones_pendientes()) == 1
    assert conector.modificaciones_pendientes() == []


def test_la_consulta_pide_los_campos_de_la_modificacion() -> None:
    for campo in (
        "BT-200-Contract",
        "BT-201-Contract",
        "BT-202-Contract",
        "modification-previous-notice-identifier",
        "BT-720-Tender",
        "notice-identifier",
    ):
        assert campo in _FIELDS
