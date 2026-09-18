"""``NoticeTypeCode`` de ``ValidNoticeInfo`` → ``licitaciones.tipos_anuncio`` (v138).

Seguimiento del spike T5 (``docs/plans/2026-09-spike-planes-anuales-placsp.md``):
el parser leía la ``IssueDate`` de cada anuncio y tiraba su código, así que no se
podía saber desde la BD si un expediente tuvo anuncio previo (``DOC_PIN*``).

El caso completo vive en el golden (``15_anuncio_previo_notice_type_code``);
aquí van los bordes y la persistencia.
"""

from __future__ import annotations

import pytest
from lxml import etree

from scraper.codice_parser import parse_entry, parse_entry_unfiltered

_CABECERA = """<entry xmlns="http://www.w3.org/2005/Atom"
  xmlns:cbc="urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2"
  xmlns:cac="urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2"
  xmlns:cacext="urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2"
  xmlns:cbcext="urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2">
  <title>Mantenimiento SAP ERP</title>
  <updated>2026-06-14T09:12:33+02:00</updated>
  <cacext:ContractFolderStatus>
    <cbc:ContractFolderID>NTC-001</cbc:ContractFolderID>
    <cbcext:ContractFolderStatusCode>PUB</cbcext:ContractFolderStatusCode>
"""
_PIE = """    <cac:ProcurementProject>
      <cbc:Name>Mantenimiento SAP ERP</cbc:Name>
    </cac:ProcurementProject>
  </cacext:ContractFolderStatus>
</entry>"""


def _bloque(codigo: str | None, fecha: str = "2026-06-01") -> str:
    codigo_xml = f"<cbcext:NoticeTypeCode>{codigo}</cbcext:NoticeTypeCode>" if codigo else ""
    return (
        f"<cacext:ValidNoticeInfo>{codigo_xml}"
        "<cacext:AdditionalPublicationStatus><cacext:AdditionalPublicationDocumentReference>"
        f"<cbc:IssueDate>{fecha}</cbc:IssueDate>"
        "</cacext:AdditionalPublicationDocumentReference></cacext:AdditionalPublicationStatus>"
        "</cacext:ValidNoticeInfo>\n"
    )


def _entry(*bloques: str) -> etree._Element:
    return etree.fromstring((_CABECERA + "".join(bloques) + _PIE).encode("utf-8"))


@pytest.mark.parametrize("parser", [parse_entry, parse_entry_unfiltered])
def test_sin_notice_type_code_queda_none_y_no_cadena_vacia(parser):
    lic = parser(_entry(_bloque(None)))
    assert lic is not None
    assert lic.tipos_anuncio is None


@pytest.mark.parametrize("parser", [parse_entry, parse_entry_unfiltered])
def test_los_codigos_se_guardan_crudos_distintos_y_ordenados(parser):
    lic = parser(
        _entry(
            _bloque("DOC_CN", "2026-06-01"),
            _bloque("DOC_PIN_RTL", "2026-03-10"),
            _bloque(" DOC_CN ", "2026-06-15"),
        )
    )
    assert lic is not None
    assert lic.tipos_anuncio == "DOC_CN,DOC_PIN_RTL"


def test_un_codigo_vacio_no_cuenta():
    lic = parse_entry(_entry(_bloque("DOC_CD"), _bloque("   ")))
    assert lic is not None
    assert lic.tipos_anuncio == "DOC_CD"


# ---------------------------------------------------------------------------
# Persistencia (Postgres)
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_db):
    db_mod, _ = tmp_db
    return db_mod


def _tipos_en_bd(id_externo: str) -> str | None:
    from db.database import connect

    with connect() as c:
        fila = c.execute(
            "SELECT tipos_anuncio FROM licitaciones WHERE id_externo = %s", (id_externo,)
        ).fetchone()
    assert fila is not None
    return fila[0]


def test_una_reingesta_sin_el_dato_no_borra_los_anuncios(db):
    from db.upsert import Licitacion, upsert_licitaciones

    base = {"id_externo": "NTC-DB-1", "titulo": "Soporte SAP", "estado": "PUB"}
    upsert_licitaciones([Licitacion(**base, tipos_anuncio="DOC_CN,DOC_PIN_RTL")])
    upsert_licitaciones([Licitacion(**base, estado="ADJ")])

    assert _tipos_en_bd("NTC-DB-1") == "DOC_CN,DOC_PIN_RTL"


def test_un_valor_nuevo_si_sustituye_al_anterior(db):
    from db.upsert import Licitacion, upsert_licitaciones

    base = {"id_externo": "NTC-DB-2", "titulo": "Soporte SAP"}
    upsert_licitaciones([Licitacion(**base, tipos_anuncio="DOC_PIN_RTL")])
    upsert_licitaciones([Licitacion(**base, tipos_anuncio="DOC_CD,DOC_CN,DOC_PIN_RTL")])

    assert _tipos_en_bd("NTC-DB-2") == "DOC_CD,DOC_CN,DOC_PIN_RTL"
