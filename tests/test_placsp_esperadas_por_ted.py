"""El expediente de PLACSP que un aviso TED enlaza entra entero aunque la puerta lo descarte.

TED entra por cualquier CPV 48/72 del aviso; PLACSP, por el principal y las
palabras clave. Un aviso TED podía enlazar (``idEvl``) un expediente que el ATOM
descartaba, y el contrato se quedaba con la versión de TED. Ahora el conector de
PLACSP lo ingiere con ``inclusion_reason = 'referencia_ted'`` y el
emparejamiento por ``idEvl`` lo hace canónica (``scraper.connectors.placsp.EsperadasPorTed``).

Los unitarios doblan la BD; los ``test_integration_*`` corren contra Postgres.
"""

from __future__ import annotations

import textwrap
from typing import Any

import pytest
from lxml import etree

from scraper.connectors.placsp import EsperadasPorTed, _PlacspParseCore

_DEEPLINK = "https://contrataciondelestado.es/wps/poc?uri=deeplink:detalle_licitacion&idEvl="
_NS = {
    "cbc": "urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2",
    "cacext": "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2",
    "cbcext": "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2",
}


def _entry_fuera_de_la_puerta() -> Any:
    """Jardinería (CPV 77, sin keyword): la puerta tecnológica la descarta."""
    deeplink = _DEEPLINK.replace("&", "&amp;")
    xml = textwrap.dedent(f"""\
        <feed xmlns="http://www.w3.org/2005/Atom">
        <entry xmlns:cbc="{_NS["cbc"]}" xmlns:cac="{_NS["cac"]}"
               xmlns:cacext="{_NS["cacext"]}" xmlns:cbcext="{_NS["cbcext"]}">
          <id>{deeplink}JARDIN%3D%3D</id>
          <title>Servicio de limpieza de jardines municipales</title>
          <updated>2026-06-14T09:12:33+02:00</updated>
          <link href="{deeplink}JARDIN%3D%3D" rel="alternate"/>
          <cacext:ContractFolderStatus>
            <cbc:ContractFolderID>2026-JARDIN</cbc:ContractFolderID>
            <cbcext:ContractFolderStatusCode>PUB</cbcext:ContractFolderStatusCode>
            <cacext:LocatedContractingParty>
              <cac:Party>
                <cac:PartyIdentification>
                  <cbc:ID schemeName="ID_PLATAFORMA">10000000000001</cbc:ID>
                </cac:PartyIdentification>
                <cac:PartyName><cbc:Name>Ayuntamiento de Prueba</cbc:Name></cac:PartyName>
              </cac:Party>
            </cacext:LocatedContractingParty>
            <cac:ProcurementProject>
              <cbc:Name>Servicio de limpieza de jardines municipales</cbc:Name>
              <cac:BudgetAmount>
                <cbc:TaxExclusiveAmount currencyID="EUR">90000.00</cbc:TaxExclusiveAmount>
              </cac:BudgetAmount>
              <cac:RequiredCommodityClassification>
                <cbc:ItemClassificationCode>77310000</cbc:ItemClassificationCode>
              </cac:RequiredCommodityClassification>
            </cac:ProcurementProject>
            <cac:LegalDocumentReference>
              <cbc:ID>PCAP.pdf</cbc:ID>
              <cac:Attachment><cac:ExternalReference>
                <cbc:URI>https://contrataciondelestado.es/pcap-jardin.pdf</cbc:URI>
                <cbc:DocumentHash>hash-pcap</cbc:DocumentHash>
              </cac:ExternalReference></cac:Attachment>
            </cac:LegalDocumentReference>
          </cacext:ContractFolderStatus>
        </entry>
        </feed>
    """)
    return etree.fromstring(xml.encode()).find("{http://www.w3.org/2005/Atom}entry")


@pytest.fixture()
def sin_ml(monkeypatch: pytest.MonkeyPatch) -> None:
    """El fallback ML tampoco la rescata: solo queda la referencia de TED."""
    monkeypatch.setattr("scraper.pipeline._ml_classify_entry", lambda entry: None)


def _core(esperadas: list[str]) -> _PlacspParseCore:
    core = _PlacspParseCore()
    core.esperadas = EsperadasPorTed(cargar=lambda: esperadas)
    return core


# ── EsperadasPorTed ──────────────────────────────────────────────────────────


def test_espera_compara_el_idevl_decodificado():
    esperadas = EsperadasPorTed(
        cargar=lambda: [f"{_DEEPLINK}CEGLc1%2fkxg%2fE6P%2fuLemXRw%3d%3d"]
    )

    # El ATOM escribe el escape en mayúsculas y TED a veces en minúsculas.
    assert esperadas.espera(f"{_DEEPLINK}CEGLc1%2Fkxg%2FE6P%2FuLemXRw%3D%3D")
    assert not esperadas.espera(f"{_DEEPLINK}OTRO")


def test_espera_carga_el_mapa_una_vez_y_no_toca_la_bd_sin_idevl():
    cargas = 0

    def cargar() -> list[str]:
        nonlocal cargas
        cargas += 1
        return [f"{_DEEPLINK}AAA"]

    esperadas = EsperadasPorTed(cargar=cargar)

    assert not esperadas.espera("https://example.com/sin-idevl")
    assert cargas == 0
    assert esperadas.espera(f"{_DEEPLINK}AAA")
    assert not esperadas.espera(f"{_DEEPLINK}BBB")
    assert cargas == 1


def test_si_la_carga_falla_no_espera_nada_y_no_lanza():
    def cargar() -> list[str]:
        raise RuntimeError("DATABASE_URL no está configurada")

    esperadas = EsperadasPorTed(cargar=cargar)

    assert not esperadas.espera(f"{_DEEPLINK}AAA")
    assert not esperadas.espera(f"{_DEEPLINK}AAA")


# ── Parseo ───────────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("sin_ml")
def test_la_entry_que_espera_un_aviso_ted_entra_entera():
    core = _core([f"{_DEEPLINK}JARDIN%3d%3d"])

    parsed = core.parse_entry_elem(_entry_fuera_de_la_puerta(), fuente="placsp")

    assert parsed is not None
    lic = parsed.licitacion
    assert lic.id_externo == "placsp:10000000000001:2026-JARDIN"
    assert lic.inclusion_reason == "referencia_ted"
    assert lic.analysis_universe == "technology_observed"
    assert lic.importe == 90000.0
    assert lic.tecnologia is None
    assert [d.uri for d in parsed.documentos] == [
        "https://contrataciondelestado.es/pcap-jardin.pdf"
    ]


@pytest.mark.usefixtures("sin_ml")
def test_la_entry_que_nadie_espera_sigue_descartada():
    core = _core([f"{_DEEPLINK}OTRA"])

    assert core.parse_entry_elem(_entry_fuera_de_la_puerta(), fuente="placsp") is None


def test_agregadas_no_consulta_los_avisos_ted(sin_ml: None):
    from scraper.connectors.placsp_agregadas import PlacspAgregadasConnector

    conector = PlacspAgregadasConnector(
        "https://contrataciondelsectorpublico.gob.es/sindicacion/sindicacion_1044/x.atom"
    )

    assert not conector._core.esperadas.espera(f"{_DEEPLINK}JARDIN%3D%3D")


# ── Recorrido real contra Postgres ───────────────────────────────────────────


@pytest.fixture()
def db(tmp_db: Any) -> Any:
    db_mod, _ = tmp_db
    return db_mod


@pytest.mark.usefixtures("sin_ml")
def test_integration_el_aviso_ted_queda_detras_del_expediente_de_placsp(
    db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime, timedelta

    from db.database import connect, connect_read
    from scraper.connectors.base import run_connector
    from scraper.connectors.placsp import PlacspAtomConnector
    from services.dedupe import reemparejar_ted_por_id_evl

    hoy = datetime.now(UTC).date()
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, importe, url, "
            "fecha_publicacion, fecha_limite, estado, fuente, fecha_extraccion, "
            "analysis_universe) VALUES (%s, %s, %s, %s, %s, %s, %s, 'PUB', 'ted', %s, "
            "'technology_observed')",
            (
                "ted:500000-2026",
                "Servicio de limpieza de jardines municipales",
                "Ayuntamiento de Prueba",
                90000.0,
                f"{_DEEPLINK}JARDIN%3d%3d",
                (hoy - timedelta(days=1)).isoformat(),
                (hoy + timedelta(days=20)).isoformat(),
                hoy.isoformat(),
            ),
        )
    monkeypatch.setattr(
        "scraper.atom_live.iter_live_entries",
        lambda **_: ([(_entry_fuera_de_la_puerta(), "2026-06-14T09:12:33+02:00")], {}),
    )

    resultado = run_connector(PlacspAtomConnector())
    reemparejo = reemparejar_ted_por_id_evl()
    # Ya emparejada, la entry sigue entrando: si no, su adjudicación se perdería.
    segunda = run_connector(PlacspAtomConnector())

    assert resultado.nuevas == 1
    assert reemparejo.confirmados == 1
    assert segunda.parsed == 1
    with connect_read() as c:
        marca = c.execute(
            "SELECT canonical_id, status FROM licitaciones_duplicados WHERE licitacion_id = %s",
            ("ted:500000-2026",),
        ).fetchone()
        pliegos = c.execute(
            "SELECT uri FROM documentos WHERE licitacion_id = %s",
            ("placsp:10000000000001:2026-JARDIN",),
        ).fetchall()
    assert tuple(marca) == ("placsp:10000000000001:2026-JARDIN", "confirmed")
    assert [p[0] for p in pliegos] == ["https://contrataciondelestado.es/pcap-jardin.pdf"]
