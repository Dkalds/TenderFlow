"""Los conectores declaran la base del importe (ADR-032, D21).

Solo ``scraper/codice_parser.py`` rellenaba ``importe_tipo``: PSCP, TED y los
RSS autonómicos escribían ``importe`` sin decir de qué base era, así que sus
filas nacían con ``importe_tipo IS NULL`` — la serie que
``scripts/audit_domain_truth.py`` vigila con umbral cero. Cada fuente publica
su importe de una forma distinta, y estos tests fijan la semántica de cada una.
"""

from __future__ import annotations

from typing import Any

from scraper.connectors.base import RawNotice
from scraper.connectors.pscp import PscpConnector, _importes
from scraper.connectors.regional_rss import _tipo_de_importe
from scraper.connectors.ted import TedConnector

_TIPOS_VALIDOS = {"sin_iva", "con_iva", "desconocido"}


# ── PSCP ─────────────────────────────────────────────────────────────────────


def _pscp(**campos: Any) -> Any:
    record = {
        "codi_expedient": "EXP-IVA",
        "objecte_contracte": "Manteniment de la plataforma SAP",
        "fase_publicacio": "Anunci de licitació",
        **campos,
    }
    parsed = PscpConnector(dataset_id="test-test").parse(
        RawNotice(natural_id="EXP-IVA", payload=record)
    )
    assert parsed is not None
    return parsed.licitacion


def test_pscp_sense_es_la_base_sin_iva_y_conserva_el_con_iva() -> None:
    lic = _pscp(pressupost_licitacio_sense="100000", pressupost_licitacio_amb="121000")
    assert lic.importe == 100000.0
    assert lic.importe_tipo == "sin_iva"
    assert lic.importe_base_sin_iva == 100000.0
    assert lic.importe_con_iva == 121000.0


def test_pscp_solo_amb_es_con_iva_y_no_se_hace_pasar_por_base() -> None:
    lic = _pscp(pressupost_licitacio_amb="121000")
    assert lic.importe == 121000.0
    assert lic.importe_tipo == "con_iva"
    assert lic.importe_base_sin_iva is None
    assert lic.importe_con_iva == 121000.0


def test_pscp_valor_estimado_es_sin_iva_pero_no_presupuesto() -> None:
    """La LCSP define el valor estimado sin IVA, pero no es el presupuesto base:
    si llegara a ``importe_base_sin_iva`` las bajas se medirían contra él."""
    lic = _pscp(valor_estimat_contracte="250000")
    assert lic.importe_tipo == "sin_iva"
    assert lic.valor_estimado == 250000.0
    assert lic.importe_base_sin_iva is None


#: Publicación agregada de un contrato menor, tal como la sirve la API Socrata
#: (expediente 2302/081 de Informació i Comunicació de Barcelona, leído el
#: 2026-11-07): sin presupuesto ni valor estimado, solo lo adjudicado.
_AGREGADA_REAL = {
    "codi_expedient": "2302/081",
    "tipus_contracte": "Subministraments",
    "procediment": "Contracte menor",
    "fase_publicacio": "Publicació agregada de contractes",
    "denominacio": "Compra de llicències Office",
    "codi_cpv": "72267000-4",
    "identificacio_adjudicatari": "B61172219",
    "denominacio_adjudicatari": "SEIDOR SOLUTIONS S.L.",
    "import_adjudicacio_sense": "769.5",
    "import_adjudicacio_amb_iva": "931.1",
    "enllac_publicacio": {
        "url": "https://contractaciopublica.cat/ca/detall-publicacio/"
        "93b05970-c56b-42d0-82b8-78d21a231f37/200070348"
    },
    "data_adjudicacio_contracte": "2023-02-23T00:00:00.000",
    "data_publicacio_contracte": "2023-06-01T12:03:00.000",
}


def test_pscp_agregada_lleva_lo_adjudicado_sin_iva_y_no_lo_hace_presupuesto() -> None:
    """Las agregadas eran el 97 % del ``desconocido`` de PSCP (2026-11-07)."""
    assert _importes(_AGREGADA_REAL) == {"importe": 769.5, "importe_tipo": "sin_iva"}


def test_pscp_agregada_parseada_entera_declara_su_base() -> None:
    parsed = PscpConnector(dataset_id="test-test").parse(
        RawNotice(
            natural_id="93b05970-c56b-42d0-82b8-78d21a231f37:2302/081", payload=_AGREGADA_REAL
        )
    )
    assert parsed is not None
    assert parsed.licitacion.importe == 769.5
    assert parsed.licitacion.importe_tipo == "sin_iva"
    assert parsed.licitacion.importe_base_sin_iva is None
    assert parsed.adjudicaciones[0].importe_adjudicado == 769.5


def test_pscp_solo_adjudicado_con_iva_es_con_iva() -> None:
    assert _importes({"import_adjudicacio_amb_iva": "931.1"}) == {
        "importe": 931.1,
        "importe_tipo": "con_iva",
    }


def test_pscp_campo_historico_sin_sufijo_es_desconocido() -> None:
    assert _importes({"pressupost_licitacio": "5000"})["importe_tipo"] == "desconocido"


def test_pscp_sin_importe_no_inventa_tipo() -> None:
    lic = _pscp()
    assert lic.importe is None
    assert lic.importe_tipo is None


# ── TED ──────────────────────────────────────────────────────────────────────


def _ted(**campos: Any) -> Any:
    notice = {
        "publication-number": "1-2026",
        "notice-type": "cn-standard",
        "notice-title": {"spa": ["Soporte SAP S/4HANA"]},
        "buyer-name": {"spa": ["Servicio Andaluz de Salud"]},
        "publication-date": "2026-06-01+02:00",
        **campos,
    }
    parsed = TedConnector().parse(RawNotice(natural_id="1-2026", payload=notice))
    assert parsed is not None
    return parsed.licitacion


def test_ted_valor_estimado_es_sin_iva_y_va_a_valor_estimado() -> None:
    lic = _ted(**{"estimated-value-proc": "4562500"})
    assert lic.importe == 4562500.0
    assert lic.importe_tipo == "sin_iva"
    assert lic.valor_estimado == 4562500.0
    assert lic.importe_base_sin_iva is None


def test_ted_valor_del_resultado_es_sin_iva_pero_no_presupuesto() -> None:
    """BT-161 sin valor estimado: forma real del 748601-2026 (2026-11-07)."""
    lic = _ted(
        **{
            "notice-type": "can-standard",
            "result-value-notice": "661676",
            "tender-value": ["661676"],
        }
    )
    assert lic.importe == 661676.0
    assert lic.importe_tipo == "sin_iva"
    assert lic.valor_estimado is None
    assert lic.importe_base_sin_iva is None


def test_ted_valor_estimado_solo_por_lote_se_suma() -> None:
    """Forma real del 509147-2026: BT-27 solo en el lote, como lista."""
    lic = _ted(
        **{
            "notice-type": "can-social",
            "estimated-value-lot": ["332089.6"],
            "estimated-value-cur-lot": ["EUR"],
            "result-value-notice": "76000",
        }
    )
    assert lic.importe == 332089.6
    assert lic.valor_estimado == 332089.6
    assert lic.importe_tipo == "sin_iva"


def test_ted_valor_estimado_de_varios_lotes_es_su_suma() -> None:
    lic = _ted(**{"estimated-value-lot": ["100000", "50000.5"]})
    assert lic.valor_estimado == 150000.5


def test_ted_un_lote_ilegible_no_da_una_suma_parcial() -> None:
    lic = _ted(**{"estimated-value-lot": ["100000", "n/d"], "result-value-notice": "90000"})
    assert lic.valor_estimado is None
    assert lic.importe == 90000.0


def test_ted_pide_el_valor_estimado_del_lote() -> None:
    from scraper.connectors.ted import _FIELDS

    assert "estimated-value-lot" in _FIELDS


def test_ted_sin_importe_no_inventa_tipo() -> None:
    lic = _ted()
    assert lic.importe is None
    assert lic.importe_tipo is None


# ── RSS autonómicos (Galicia, Euskadi) ───────────────────────────────────────


def test_rss_sin_mencion_de_iva_es_desconocido() -> None:
    assert _tipo_de_importe("Importe: 2.364.210,48 €", 2364210.48) == "desconocido"


def test_rss_declara_sin_iva_en_las_lenguas_de_los_feeds() -> None:
    for texto in (
        "Importe (sin IVA): 1.000 €",
        "Importe sen IVE: 1.000 €",
        "Import sense IVA: 1.000 €",
        "Importe IVA excluido: 1.000 €",
        "Zenbatekoa (BEZ gabe): 1.000 €",
    ):
        assert _tipo_de_importe(texto, 1000.0) == "sin_iva", texto


def test_rss_declara_con_iva() -> None:
    assert _tipo_de_importe("Importe (IVA incluido): 1.210 €", 1210.0) == "con_iva"
    assert _tipo_de_importe("Importe con IVA: 1.210 €", 1210.0) == "con_iva"


def test_rss_las_dos_menciones_no_permiten_afirmar_la_base() -> None:
    texto = "Importe sin IVA: 1.000 €. Importe con IVA: 1.210 €"
    assert _tipo_de_importe(texto, 1000.0) == "desconocido"


def test_rss_sin_importe_no_hay_tipo() -> None:
    assert _tipo_de_importe("Sin importe publicado", None) is None


def test_rss_la_fila_de_galicia_lleva_tipo() -> None:
    from scraper.connectors.galicia import GaliciaRssConnector

    connector = GaliciaRssConnector()
    parsed = connector.parse(
        RawNotice(
            natural_id="1",
            payload={
                "title": "Servizo de mantemento SAP - ID: 1",
                "description": "<p><b>Importe:</b> 2.364.210,48 &euro; (sen IVE)</p>",
                "published": "2026-07-29T07:53:00+00:00",
                "link": "https://www.contratosdegalicia.gal/licitacion?N=1",
            },
        )
    )
    assert parsed is not None
    assert parsed.licitacion.importe_tipo in _TIPOS_VALIDOS
    assert parsed.licitacion.importe_tipo == "sin_iva"
    assert parsed.licitacion.importe_base_sin_iva == 2364210.48
