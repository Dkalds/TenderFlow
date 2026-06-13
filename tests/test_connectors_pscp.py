"""Tests del conector PSCP Catalunya (Fase 5, RFC 20260611-1)."""

from __future__ import annotations

import pytest

from scraper.connectors.base import RawNotice
from scraper.connectors.pscp import PscpConnector, _fase_to_estado, _field, _number

# ---------------------------------------------------------------------------
# Fixtures: registro Socrata con los nombres de campo candidatos
# ---------------------------------------------------------------------------


def _pscp_record():
    # Nombres de campo del dataset real ybgg-dgi6 (probe del 2026-06-11)
    return {
        "codi_expedient": "CTTI-2026-00123",
        "objecte_contracte": "Implantació i suport de SAP S/4HANA al CTTI",
        "nom_organ": "Centre de Telecomunicacions i Tecnologies de la Informació",
        "data_publicacio_anunci": "2026-05-20T00:00:00.000",
        "termini_presentacio_ofertes": "2026-06-15T14:00:00.000",
        "pressupost_licitacio_sense": "1250000.50",
        "codi_cpv": "72000000, 48000000",
        "codi_nuts": "ES511",
        "tipus_contracte": "Serveis",
        "fase_publicacio": "Anunci de licitació",
        "enllac_publicacio": {"url": "https://contractaciopublica.cat/ca/detall/123"},
    }


def test_pscp_parse_anuncio_licitacion():
    parsed = PscpConnector(dataset_id="test-test").parse(
        RawNotice(natural_id="CTTI-2026-00123", payload=_pscp_record())
    )

    lic = parsed.licitacion
    assert lic.id_externo == "pscp:CTTI-2026-00123"
    assert lic.fuente == "pscp"
    assert lic.estado == "PUB"
    assert lic.titulo.startswith("Implantació i suport de SAP")
    assert lic.organo_contratacion.startswith("Centre de Telecomunicacions")
    assert lic.importe == 1250000.50
    assert lic.cpv == "72000000"  # primer CPV de la lista
    assert lic.fecha_publicacion == "2026-05-20"
    assert lic.fecha_limite == "2026-06-15"
    assert lic.url == "https://contractaciopublica.cat/ca/detall/123"
    assert lic.nuts_code == "ES511"  # codi_nuts real de la fila
    assert lic.ccaa == "Cataluña"
    assert "SAP" in (lic.tecnologia or "")  # char_wb detecta SAP en catalán
    assert parsed.adjudicaciones == []


def test_pscp_parse_adjudicacion_crea_adjudicacion():
    record = _pscp_record()
    record["fase_publicacio"] = "Adjudicació"
    record["denominacio_adjudicatari"] = "Seidor Consulting SL"
    record["identificacio_adjudicatari"] = "B-61420352"
    record["import_adjudicacio_sense"] = "990000"
    record["ofertes_rebudes"] = "4"
    record["data_adjudicacio_contracte"] = "2026-08-01T00:00:00.000"

    parsed = PscpConnector(dataset_id="test-test").parse(
        RawNotice(natural_id="CTTI-2026-00123", payload=record)
    )

    assert parsed.licitacion.estado == "ADJ"
    assert len(parsed.adjudicaciones) == 1
    adj = parsed.adjudicaciones[0]
    assert adj.nombre == "Seidor Consulting SL"
    assert adj.nif == "B-61420352"
    assert adj.importe_adjudicado == 990000.0
    assert adj.n_ofertas_recibidas == 4
    assert adj.fecha_adjudicacion == "2026-08-01"
    assert adj.licitacion_id == "pscp:CTTI-2026-00123"


def test_pscp_parse_sin_titulo_descarta():
    record = {"codi_expedient": "X-1", "fase_publicacio": "Anunci"}
    assert PscpConnector(dataset_id="t-t").parse(RawNotice("X-1", record)) is None


def test_fase_to_estado_mapea_fases_catalanas():
    assert _fase_to_estado("Anunci de licitació") == "PUB"
    assert _fase_to_estado("Anunci previ") == "PRE"
    assert _fase_to_estado("Adjudicació") == "ADJ"
    assert _fase_to_estado("Formalització") == "RES"
    assert _fase_to_estado("Anul·lació") == "ANUL"
    assert _fase_to_estado(None) is None
    # Fase desconocida: se conserva cruda (truncada), no se pierde
    assert _fase_to_estado("Fase rara") == "FASE RARA"


def test_field_candidates_y_number():
    record = {"pressupost_licitacio_amb": "1512500.61"}  # solo segundo candidato
    assert _field(record, "importe") == "1512500.61"
    assert _number({"pressupost_licitacio_sense": "1250000.50"}, "importe") == 1250000.50
    assert _number({"pressupost_licitacio_sense": "n/d"}, "importe") is None


def test_pscp_since_aplica_solape_de_un_dia():
    connector = PscpConnector(dataset_id="t-t")
    assert connector._since({"last_seen_updated": "2026-06-10"}) == "2026-06-09"
    assert len(connector._since(None)) == 10  # lookback por defecto YYYY-MM-DD


def test_pscp_fetch_sin_dataset_falla_claro(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "PSCP_DATASET_ID", "")
    connector = PscpConnector(dataset_id="")
    with pytest.raises(RuntimeError, match="PSCP_DATASET_ID"):
        list(connector.fetch(None))


def test_pscp_dataset_default_validado():
    # ybgg-dgi6 = "Contractació pública: publicacions a la PSCP" (portal oficial)
    assert PscpConnector().dataset_id == "ybgg-dgi6"


def test_pscp_fetch_pagina_y_avanza_cursor():
    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class FakeSession:
        def __init__(self, pages):
            self.pages = pages
            self.calls = []

        def get(self, url, *, params, headers, timeout):
            self.calls.append(params)
            return FakeResponse(self.pages[len(self.calls) - 1])

    rec1 = dict(_pscp_record(), **{":updated_at": "2026-05-21T08:00:00.000Z"})
    rec2 = dict(_pscp_record(), codi_expedient="X-2", **{":updated_at": "2026-05-22T09:00:00.000Z"})
    session = FakeSession(pages=[[rec1, rec2]])
    connector = PscpConnector(dataset_id="abcd-1234", session=session)

    notices = list(connector.fetch({"last_seen_updated": "2026-05-21"}))

    assert [n.natural_id for n in notices] == ["CTTI-2026-00123", "X-2"]
    assert connector.new_cursor() == {"last_seen_updated": "2026-05-22"}
    where = session.calls[0]["$where"]
    assert ":updated_at >= '2026-05-20'" in where  # solape de 1 día
