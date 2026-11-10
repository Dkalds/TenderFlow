"""``cac:ContractModification`` → ``contrato_modificaciones`` (v180).

Sobre expedientes reales del corpus (``tests/fixtures/placsp``).
"""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from scraper.codice_parser import parse_modificaciones

_FIXTURES = Path(__file__).parent / "fixtures" / "placsp"
_ATOM = "{http://www.w3.org/2005/Atom}entry"


def _entry(nombre: str) -> etree._Element:
    raiz = etree.parse(str(_FIXTURES / nombre)).getroot()
    return raiz if raiz.tag == _ATOM else next(raiz.iter(_ATOM))


def test_dos_prorrogas_del_lote_1_con_sus_importes_sin_iva() -> None:
    # B070005/2022-0071: dos prórrogas de un año del lote 1, un solo anuncio DOC_MOD.
    primera, segunda = parse_modificaciones(_entry("25_multilote_real_por_lote.xml"), "placsp:O:E")

    assert primera.clave == "placsp:O:E#B070005/2022-0071 L1#1"
    assert (primera.fuente, primera.licitacion_id, primera.enlace) == (
        "placsp",
        "placsp:O:E",
        "fuente",
    )
    assert primera.contrato_ref == "B070005/2022-0071 L1"
    # El lote sale de la adjudicación cuyo `cac:Contract/cbc:ID` es el `ContractID`.
    assert primera.lote_numero == "1"
    assert primera.motivo == "1ª Prórroga prevista en el contrato"
    assert (primera.importe_modificacion, primera.importe_final) == (188800.89, 377601.79)
    assert primera.importe_modificacion_base == primera.importe_final_base == "sin_iva"
    assert primera.moneda == "EUR"
    assert (primera.plazo_modificacion, primera.plazo_final, primera.plazo_unidad) == (
        1.0,
        2.0,
        "ANN",
    )
    # La segunda no trae `cbc:Note`: sin motivo, no uno inventado.
    assert segunda.numero == "2"
    assert segunda.motivo is None
    assert segunda.importe_final == 566402.68


def test_un_anuncio_para_dos_modificaciones_no_reparte_fechas() -> None:
    modificaciones = parse_modificaciones(_entry("25_multilote_real_por_lote.xml"), "placsp:O:E")

    assert [m.fecha_publicacion for m in modificaciones] == [None, None]


def test_un_expediente_sin_modificaciones_no_devuelve_ninguna() -> None:
    assert parse_modificaciones(_entry("24_documentos_real.xml"), "placsp:O:E") == []
