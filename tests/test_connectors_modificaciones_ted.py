"""Los avisos ``can-modif`` de TED son modificaciones, no licitaciones (v180, CU-38).

Los avisos son respuestas reales de la API de búsqueda, guardadas el
2026-11-10 en ``tests/fixtures/ted/modificaciones_reales.json``: dos
modificaciones encadenadas del Ajuntament de Sabadell (718637-2026 modifica
786-2026, que modifica la adjudicación 871071-2025, guardada como
``_aviso_original_referencia``). La API se sustituye por una sesión que
contesta con esos mismos avisos.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from scraper.connectors.base import RawNotice
from scraper.connectors.ted import _FIELDS, TedConnector, _sin_ceros

_RESPUESTA = json.loads(
    (Path(__file__).parent / "fixtures" / "ted" / "modificaciones_reales.json").read_text("utf-8")
)
_AVISOS: dict[str, dict[str, Any]] = {a["publication-number"]: a for a in _RESPUESTA["notices"]}
_POR_UUID = {
    a["notice-identifier"]: a
    for a in [*_RESPUESTA["notices"], _RESPUESTA["_aviso_original_referencia"]]
}


class _Respuesta:
    def __init__(self, cuerpo: dict[str, Any]) -> None:
        self._cuerpo = cuerpo

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._cuerpo


class _SesionTed:
    """Contesta ``notice-identifier IN (…)`` con los avisos guardados."""

    def __init__(self, *, falla: bool = False) -> None:
        self.consultas: list[str] = []
        self.falla = falla

    def post(self, _url: str, *, json: dict[str, Any], timeout: float) -> _Respuesta:
        del timeout
        self.consultas.append(json["query"])
        if self.falla:
            raise ConnectionError("sin red")
        uuids = re.findall(r"[0-9a-f-]{36}", json["query"])
        return _Respuesta({"notices": [_POR_UUID[u] for u in uuids if u in _POR_UUID]})


def _pendientes(*numeros: str, sesion: _SesionTed | None = None) -> list[Any]:
    conector = TedConnector(session=sesion or _SesionTed())  # type: ignore[arg-type]
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
    # El enlace es el aviso, no los pliegos.
    assert modificacion.url == "https://ted.europa.eu/es/notice/786-2026/pdf"
    # BT-04: Sabadell no publica BT-22, y su procedimiento es la ficha de la plataforma catalana.
    assert modificacion.procedimiento_ref == "2b7d8b43-35dc-4277-85d7-bce5a45b9016"


def test_bt720_es_el_valor_del_aviso_sin_base_y_no_el_importe_final() -> None:
    [modificacion] = _pendientes("786-2026")

    assert (modificacion.importe_aviso, modificacion.importe_aviso_base) == (
        320477.0,
        "desconocido",
    )
    assert modificacion.importe_final is None
    assert modificacion.importe_modificacion is None


def test_el_uuid_del_aviso_original_se_traduce_a_su_numero() -> None:
    primera, segunda = _pendientes("786-2026", "718637-2026")

    # La primera modifica la adjudicación; la segunda, la primera modificación.
    assert primera.aviso_original == "871071-2025"
    assert segunda.aviso_original == "786-2026"
    assert primera.identificador_aviso == "be80e249-3d04-4f02-91f7-761b9ad0ed4f"


def test_sin_api_el_aviso_original_se_queda_como_uuid() -> None:
    sesion = _SesionTed(falla=True)
    [modificacion] = _pendientes("786-2026", sesion=sesion)

    assert modificacion.aviso_original == "cb2be52c-ecc0-4a3d-be12-af16ec0b3b6b-01"
    assert sesion.consultas == ["notice-identifier IN (cb2be52c-ecc0-4a3d-be12-af16ec0b3b6b)"]


def test_los_ceros_a_la_izquierda_del_numero_de_aviso_se_quitan() -> None:
    assert _sin_ceros("00023108-2025") == "23108-2025"
    assert _sin_ceros("871071-2025") == "871071-2025"
    assert _sin_ceros("cb2be52c-ecc0-4a3d-be12-af16ec0b3b6b-01") == (
        "cb2be52c-ecc0-4a3d-be12-af16ec0b3b6b-01"
    )


def test_el_bufer_se_vacia_al_leerlo() -> None:
    conector = TedConnector(session=_SesionTed())  # type: ignore[arg-type]
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
        "procedure-identifier",
    ):
        assert campo in _FIELDS
