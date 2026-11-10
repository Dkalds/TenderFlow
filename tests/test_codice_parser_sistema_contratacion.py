"""``cbc:ContractingSystemCode`` → ``licitaciones.sistema_contratacion`` (v178).

Los casos «basado» salen de expedientes reales del corpus (``tests/fixtures/placsp``);
el establecimiento de un marco o de un SDA no está en él, así que esos dos
códigos se prueban con una entry mínima y la lista oficial delante
(``shared/sistema_contratacion.py``).
"""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest
from lxml import etree

from scraper.codice_parser import parse_entry, parse_entry_unfiltered
from shared.sistema_contratacion import BASADOS, MARCOS, SISTEMAS, desde_codice

_FIXTURES = Path(__file__).parent / "fixtures" / "placsp"

_ENTRY = """<entry xmlns="http://www.w3.org/2005/Atom"
  xmlns:cbc="urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2"
  xmlns:cac="urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2"
  xmlns:cacext="urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2">
  <title>Acuerdo marco de servicios de desarrollo SAP</title>
  <updated>2026-06-14T09:12:33+02:00</updated>
  <cacext:ContractFolderStatus>
    <cbc:ContractFolderID>AM-001</cbc:ContractFolderID>
    <cac:ProcurementProject><cbc:Name>Acuerdo marco de servicios de desarrollo SAP</cbc:Name></cac:ProcurementProject>
    <cac:TenderingProcess>{codigo}</cac:TenderingProcess>
  </cacext:ContractFolderStatus>
</entry>"""


def _entry(codigo: str | None) -> etree._Element:
    xml = f"<cbc:ContractingSystemCode>{codigo}</cbc:ContractingSystemCode>" if codigo else ""
    return etree.fromstring(_ENTRY.format(codigo=xml).encode("utf-8"))


def _real(nombre: str) -> etree._Element:
    raiz = etree.parse(str(_FIXTURES / nombre)).getroot()
    if raiz.tag == "{http://www.w3.org/2005/Atom}entry":
        return raiz
    return next(raiz.iter("{http://www.w3.org/2005/Atom}entry"))


@pytest.mark.parametrize(
    ("fixture", "esperado"),
    [
        # CBA4573/2026, «… Am02 Lote 4»: basado en el AM 02 de la DGRCC.
        ("22_pyme_real.xml", "basado_marco"),
        # CESDA 1750/2026, «Contrato específico basado en el SDA-TIC 3-23 CC».
        ("20_lotes_repiten_presupuesto_real.xml", "basado_sda"),
        ("23_ambos_periodos_real.xml", "basado_sda"),
        ("24_documentos_real.xml", "basado_sda"),
        # Un abierto corriente publica «0»: la fuente dice que no aplica.
        ("21_solvencia_umbral_real.xml", "ninguno"),
    ],
)
def test_expedientes_reales(fixture: str, esperado: str) -> None:
    lic = parse_entry_unfiltered(_real(fixture))
    assert lic is not None
    assert lic.sistema_contratacion == esperado


@pytest.mark.parametrize("parser", [parse_entry, parse_entry_unfiltered])
@pytest.mark.parametrize(
    ("codigo", "esperado"),
    [("1", "marco"), ("2", "sda"), ("3", "basado_marco"), ("4", "basado_sda"), ("0", "ninguno")],
)
def test_cada_codigo_de_la_lista(parser, codigo: str, esperado: str) -> None:
    lic = parser(_entry(codigo))
    assert lic is not None
    assert lic.sistema_contratacion == esperado


@pytest.mark.parametrize("codigo", [None, "9", "AM"])
def test_sin_codigo_o_con_uno_desconocido_queda_sin_dato(codigo: str | None) -> None:
    """Un código que la lista no trae no se asimila a «ninguno»: no se sabe."""
    lic = parse_entry_unfiltered(_entry(codigo))
    assert lic is not None
    assert lic.sistema_contratacion is None


def test_el_vocabulario_separa_marcos_de_basados() -> None:
    assert MARCOS | BASADOS | {"ninguno"} == set(SISTEMAS)
    assert not MARCOS & BASADOS
    assert desde_codice(" 3 ") == "basado_marco"


def test_el_upsert_lo_escribe_y_no_lo_nulea_al_reingerir() -> None:
    """Cuelga de ``cac:TenderingProcess``, como ``procedimiento``: mismo COALESCE."""
    from db.models import licitaciones
    from db.upsert import _LIC_COALESCE_UPDATE_FIELDS, _LIC_KEYS, _LIC_UPDATES, Licitacion

    columna = "sistema_contratacion"
    assert columna in {f.name for f in fields(Licitacion)}
    assert columna in _LIC_KEYS
    assert columna in _LIC_COALESCE_UPDATE_FIELDS
    assert f"{columna}=COALESCE(excluded.{columna}, licitaciones.{columna})" in _LIC_UPDATES
    assert columna in licitaciones.c
