"""``cac:ContractModification`` → ``contrato_modificaciones`` (v180).

Sobre expedientes reales del corpus (``tests/fixtures/placsp``): el 25 (ZIP
2026-06) y los 26 a 28, entries del ZIP 2026-10 elegidas en la medición del
2026-11-10 por lo que tienen de raro.
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


def test_cada_lote_su_contrato_y_las_fechas_del_perfil_por_orden() -> None:
    # S-03913-2023: dos prórrogas por lote, con `ContractID` distinto por lote y
    # cuatro fechas del `DOC_MOD` del perfil para cuatro modificaciones.
    modificaciones = parse_modificaciones(_entry("26_modificaciones_por_lote_real.xml"), "X")

    assert [
        (m.contrato_ref, m.numero, m.lote_numero, m.fecha_publicacion) for m in modificaciones
    ] == [
        ("S-03913-2023-2", "1", "2", "2025-06-11"),
        ("S-03913-2023-1", "1", "1", "2025-06-19"),
        ("S-03913-2023-2", "2", "2", "2026-09-17"),
        ("S-03913-2023-1", "2", "1", "2026-10-01"),
    ]
    # Una modificación a la baja se guarda tal cual, con su signo.
    assert modificaciones[1].importe_modificacion == -8200.0


def test_dos_lotes_con_el_mismo_contrato_no_inventan_lote_ni_pisan_claves() -> None:
    # S-06722-2023: los dos lotes publican el mismo `ContractID` y cada uno su
    # modificación 1 y 2; el lote solo lo dice el `Note`. El `DOC_MOD` del perfil
    # trae cinco fechas para cuatro modificaciones: sin fecha.
    modificaciones = parse_modificaciones(
        _entry("27_modificaciones_contrato_compartido_real.xml"), "X"
    )

    assert len({m.clave for m in modificaciones}) == 4
    assert {m.lote_numero for m in modificaciones} == {None}
    assert {m.fecha_publicacion for m in modificaciones} == {None}
    # `ANN` para el plazo añadido y `MON` para el final: ninguna unidad vale para los dos.
    segunda = next(m for m in modificaciones if m.importe_final == 1182444.96)
    assert (segunda.plazo_modificacion, segunda.plazo_final, segunda.plazo_unidad) == (
        None,
        None,
        None,
    )


def test_una_resolucion_con_final_a_cero_no_es_un_contrato_gratis() -> None:
    # AGP-165/2025: una suspensión sin importes y una resolución que publica el final a 0.
    suspension, resolucion = parse_modificaciones(
        _entry("28_modificaciones_sin_importes_real.xml"), "X"
    )

    assert suspension.importe_modificacion is None and suspension.importe_final is None
    assert suspension.importe_modificacion_base is None
    assert resolucion.importe_modificacion == -714954.12
    assert (resolucion.importe_final, resolucion.importe_final_base) == (None, None)


_ENTRY_DOS_CONTRATOS = """<entry xmlns="http://www.w3.org/2005/Atom"
  xmlns:cbc="urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2"
  xmlns:cac="urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2"
  xmlns:cacext="urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2"
  xmlns:cbcext="urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2">
  <cacext:ContractFolderStatus>
    <cacext:ValidNoticeInfo>
      <cbcext:NoticeTypeCode>DOC_MOD</cbcext:NoticeTypeCode>
      <cacext:AdditionalPublicationStatus>
        <cbcext:PublicationMediaName>Perfil del contratante</cbcext:PublicationMediaName>
        {fechas}
      </cacext:AdditionalPublicationStatus>
    </cacext:ValidNoticeInfo>
    {bloques}
  </cacext:ContractFolderStatus>
</entry>"""


def _entry_sintetica(orden: list[tuple[str, str]]) -> etree._Element:
    fechas = "".join(
        f"<cacext:AdditionalPublicationDocumentReference><cbc:IssueDate>2024-0{i + 1}-01"
        "</cbc:IssueDate></cacext:AdditionalPublicationDocumentReference>"
        for i in range(len(orden))
    )
    bloques = "".join(
        f"<cac:ContractModification><cbc:ID>{n}</cbc:ID><cbc:ContractID>{c}</cbc:ContractID>"
        "</cac:ContractModification>"
        for c, n in orden
    )
    return etree.fromstring(_ENTRY_DOS_CONTRATOS.format(fechas=fechas, bloques=bloques).encode())


def test_contratos_a_ritmos_distintos_no_cruzan_fechas() -> None:
    # A1, A2, A3 y luego B1: por número saldría A1, B1, A2, A3, y B1 se quedaría
    # con la fecha de A2. Sin cronología fiable, sin fecha.
    entry = _entry_sintetica([("A", "1"), ("A", "2"), ("A", "3"), ("B", "1")])

    assert {m.fecha_publicacion for m in parse_modificaciones(entry, "X")} == {None}


def test_en_orden_de_numero_las_fechas_van_por_posicion() -> None:
    entry = _entry_sintetica([("A", "1"), ("B", "1"), ("A", "2")])

    assert [
        (m.contrato_ref, m.numero, m.fecha_publicacion) for m in parse_modificaciones(entry, "X")
    ] == [
        ("A", "1", "2024-01-01"),
        ("B", "1", "2024-02-01"),
        ("A", "2", "2024-03-01"),
    ]
