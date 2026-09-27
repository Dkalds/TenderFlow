"""La puerta tecnológica de PSCP también decide en PLACSP (2026-09-27).

Hasta hoy, `parse_entry` admitía por keyword cualquier aviso de PLACSP cuyo
título **o `atom:summary`** casara con el diccionario. Dos consecuencias,
comprobadas ejecutando el matcher:

1. El `summary` de PLACSP no es una descripción: es
   ``Id licitación: …; Órgano de Contratación: …; Importe: …; Estado: …``. El
   nombre del órgano actuaba de keyword, así que la limpieza de una sede del
   Instituto Nacional de Ciberseguridad salía `CIBERSEGURIDAD`.
2. La corroboración por CPV de las keywords ambiguas vivía solo en el conector
   de PSCP: en PLACSP, «mantenimiento correctivo de ascensores» salía
   `DESARROLLO`.

Lo que fija este módulo: el título es el único texto que decide, y la misma
puerta (`scraper.puerta_tecnologica.senal_tecnologica`) decide en las dos
fuentes, mirando **todos** los CPV del aviso y no solo el primero.
"""

from __future__ import annotations

import textwrap
from collections.abc import Iterator

import pytest
from lxml import etree

from scraper.codice_parser import parse_entry

_NS = {
    "cbc": "urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2",
    "cacext": "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2",
    "cbcext": "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2",
}


@pytest.fixture(autouse=True)
def _desde_la_semilla(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Cada test ve la semilla, no la tabla, y parte de la caché vacía."""
    import services.tecnologias_diccionario as mod

    monkeypatch.setattr(mod, "_leer", lambda: (mod.semilla(), mod._hash_de(mod.semilla())))
    mod.invalidar()
    yield
    mod.invalidar()


def _entry(titulo: str, cpvs: list[str], organo: str = "Ayuntamiento de Pinto") -> etree._Element:
    """Una <entry> CODICE mínima, con tantos CPV como se pidan."""
    clasificaciones = "".join(
        "<cac:RequiredCommodityClassification>"
        f"<cbc:ItemClassificationCode>{cpv}</cbc:ItemClassificationCode>"
        "</cac:RequiredCommodityClassification>"
        for cpv in cpvs
    )
    xml = textwrap.dedent(f"""\
        <feed xmlns="http://www.w3.org/2005/Atom">
        <entry xmlns:cbc="{_NS["cbc"]}" xmlns:cac="{_NS["cac"]}"
               xmlns:cacext="{_NS["cacext"]}" xmlns:cbcext="{_NS["cbcext"]}">
          <id>https://example.com/EXP-1</id>
          <title>{titulo}</title>
          <updated>2026-09-20T00:00:00Z</updated>
          <summary>Id licitación: EXP-1; Órgano de Contratación: {organo}; Importe: 1000 EUR; Estado: PUB</summary>
          <cacext:ContractFolderStatus>
            <cbc:ContractFolderID>EXP-1</cbc:ContractFolderID>
            <cbcext:ContractFolderStatusCode>PUB</cbcext:ContractFolderStatusCode>
            <cacext:LocatedContractingParty><cac:Party><cac:PartyName>
              <cbc:Name>{organo}</cbc:Name>
            </cac:PartyName></cac:Party></cacext:LocatedContractingParty>
            <cac:ProcurementProject>
              <cbc:Name>{titulo}</cbc:Name>
              <cbc:TypeCode>2</cbc:TypeCode>
              {clasificaciones}
            </cac:ProcurementProject>
          </cacext:ContractFolderStatus>
        </entry>
        </feed>
    """)
    raiz = etree.fromstring(xml.encode())
    entry = raiz.find("{http://www.w3.org/2005/Atom}entry")
    assert entry is not None
    return entry


class TestSummary:
    def test_el_nombre_del_organo_no_es_una_keyword(self) -> None:
        entry = _entry(
            "Servicio de limpieza de la sede de León",
            ["90910000-9"],
            organo="Instituto Nacional de Ciberseguridad de España",
        )
        assert parse_entry(entry) is None

    def test_el_titulo_sigue_decidiendo(self) -> None:
        lic = parse_entry(_entry("Mantenimiento de SAP S/4HANA", ["72267000-4"]))
        assert lic is not None
        assert lic.tecnologia == "SAP"


class TestAmbiguasEnPlacsp:
    def test_una_ambigua_con_cpv_ajeno_a_ti_no_entra(self) -> None:
        entry = _entry("Servicio de mantenimiento correctivo de ascensores", ["50750000-7"])
        assert parse_entry(entry) is None

    def test_una_ambigua_con_cpv_de_ti_entra(self) -> None:
        lic = parse_entry(
            _entry("Mantenimiento correctivo de la aplicación de nóminas", ["72267000-4"])
        )
        assert lic is not None
        assert "DESARROLLO" in (lic.tecnologia or "")

    def test_mira_todos_los_cpv_no_solo_el_primero(self) -> None:
        lic = parse_entry(
            _entry(
                "Mantenimiento correctivo de la aplicación de nóminas",
                ["79000000-4", "72267000-4"],
            )
        )
        assert lic is not None

    def test_una_keyword_no_ambigua_entra_con_cualquier_cpv(self) -> None:
        """Los contratos menores traen CPV absurdos: una sola keyword fuera de la
        lista basta, como en PSCP."""
        lic = parse_entry(_entry("Licencias de Oracle Database", ["33696500-0"]))
        assert lic is not None
        assert lic.tecnologia == "ORACLE"


class TestUnaSolaPuerta:
    def test_pscp_y_placsp_deciden_con_la_misma_funcion(self) -> None:
        import scraper.connectors.pscp as pscp
        import scraper.puerta_tecnologica as puerta

        assert pscp.senal_tecnologica is puerta.senal_tecnologica
        assert pscp.KEYWORDS_AMBIGUAS is puerta.KEYWORDS_AMBIGUAS
