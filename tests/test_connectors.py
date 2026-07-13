"""Tests del framework de conectores (ADR-009) y del conector TED."""

from __future__ import annotations

import pytest

from scraper.connectors.base import ParsedTender, RawNotice, run_connector
from scraper.connectors.ted import TedConnector, _first_lang, _nuts_provincial

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_db):
    db_mod, _ = tmp_db
    return db_mod


class FakeConnector:
    """Conector mínimo en memoria para probar el runner."""

    source_id = "fake"

    def __init__(self, notices, *, fail_fetch_after: int | None = None):
        self.notices = notices
        self.fail_fetch_after = fail_fetch_after
        self.received_cursor = "UNSET"

    def fetch(self, cursor):
        self.received_cursor = cursor
        for i, n in enumerate(self.notices):
            if self.fail_fetch_after is not None and i >= self.fail_fetch_after:
                raise RuntimeError("fetch roto")
            yield RawNotice(natural_id=n["id"], payload=n)

    def parse(self, raw):
        from db.upsert import Adjudicacion, DocumentoReferencia, Licitacion

        if raw.payload.get("explota"):
            raise ValueError("payload corrupto")
        if raw.payload.get("descartar"):
            return None
        lic = Licitacion(
            id_externo=f"fake:{raw.natural_id}",
            titulo=raw.payload["titulo"],
            fuente="fake",
            fecha_publicacion="2026-01-15",
        )
        adjs = []
        if raw.payload.get("ganador"):
            adjs.append(
                Adjudicacion(
                    licitacion_id=lic.id_externo,
                    nombre=raw.payload["ganador"],
                    importe_adjudicado=1000.0,
                    fecha_adjudicacion="2026-02-01",
                )
            )
        docs = []
        if raw.payload.get("documentos"):
            docs = [
                DocumentoReferencia(tipo=d["tipo"], uri=d["uri"], filename=d.get("filename"))
                for d in raw.payload["documentos"]
            ]
        return ParsedTender(licitacion=lic, adjudicaciones=adjs, documentos=docs)

    def new_cursor(self):
        return {"last_seen_updated": "2026-01-31"}


# ---------------------------------------------------------------------------
# Runner genérico
# ---------------------------------------------------------------------------


def test_runner_persiste_y_avanza_cursor(db):
    from db.database import connect, get_cursor

    notices = [
        {"id": "N1", "titulo": "Aviso uno"},
        {"id": "N2", "titulo": "Aviso dos", "ganador": "Ganadora SL"},
        {"id": "N3", "descartar": True, "titulo": "-"},
    ]
    result = run_connector(FakeConnector(notices))

    assert result.fetched == 3
    assert result.nuevas == 2
    assert result.descartadas == 1
    assert result.adjudicaciones == 1
    with connect() as c:
        ids = {r[0] for r in c.execute("SELECT id_externo FROM licitaciones").fetchall()}
        fuentes = {r[0] for r in c.execute("SELECT DISTINCT fuente FROM licitaciones").fetchall()}
        # La adjudicación queda enlazada al maestro por el post-ingestion hook
        linked = c.execute(
            "SELECT COUNT(*) FROM adjudicaciones WHERE empresa_id IS NOT NULL"
        ).fetchone()[0]
    assert ids == {"fake:N1", "fake:N2"}
    assert fuentes == {"fake"}
    assert linked == 1
    assert get_cursor("fake")["last_seen_updated"] == "2026-01-31"


def test_runner_es_idempotente(db):
    notices = [{"id": "N1", "titulo": "Aviso uno"}]
    run_connector(FakeConnector(notices))
    result2 = run_connector(FakeConnector(notices))

    assert result2.nuevas == 0
    from db.database import connect

    with connect() as c:
        assert c.execute("SELECT COUNT(*) FROM licitaciones").fetchone()[0] == 1


def test_runner_parse_roto_va_a_dlq_sin_abortar(db):
    from db.database import connect

    notices = [
        {"id": "N1", "titulo": "Bueno"},
        {"id": "N2", "explota": True},
        {"id": "N3", "titulo": "También bueno"},
    ]
    result = run_connector(FakeConnector(notices))

    assert result.nuevas == 2
    assert result.errores == 1
    with connect() as c:
        dlq = c.execute("SELECT fuente, scope, payload_ref FROM failed_extractions").fetchall()
    assert ("fake", "parse", "N2") in dlq


def test_runner_fetch_roto_no_avanza_cursor(db):
    from db.database import get_cursor

    notices = [{"id": "N1", "titulo": "Uno"}, {"id": "N2", "titulo": "Dos"}]
    result = run_connector(FakeConnector(notices, fail_fetch_after=1))

    assert result.errores >= 1
    assert get_cursor("fake") is None  # cursor intacto


def test_runner_pasa_cursor_al_conector(db):
    from db.database import set_cursor

    set_cursor("fake", last_seen_updated="2025-12-01")
    fake = FakeConnector([])
    run_connector(fake)
    assert fake.received_cursor["last_seen_updated"] == "2025-12-01"


# ---------------------------------------------------------------------------
# Persistencia de documentos (plan Pliegos+RAG, F6)
# ---------------------------------------------------------------------------


def test_runner_persiste_metadatos_de_documentos(db):
    from db.database import connect

    notices = [
        {
            "id": "N1",
            "titulo": "Aviso con pliegos",
            "documentos": [
                {"tipo": "legal", "uri": "https://x/pcap.pdf", "filename": "PCAP.pdf"},
                {"tipo": "technical", "uri": "https://x/ptt.pdf"},
            ],
        },
        {"id": "N2", "titulo": "Aviso sin pliegos"},
    ]
    run_connector(FakeConnector(notices))

    with connect() as c:
        rows = c.execute(
            "SELECT licitacion_id, tipo, uri, status FROM documentos ORDER BY tipo"
        ).fetchall()
    assert rows == [
        ("fake:N1", "legal", "https://x/pcap.pdf", "pending"),
        ("fake:N1", "technical", "https://x/ptt.pdf", "pending"),
    ]


def test_runner_documentos_reingesta_no_duplica(db):
    from db.database import connect

    notices = [
        {
            "id": "N1",
            "titulo": "Aviso con pliegos",
            "documentos": [{"tipo": "legal", "uri": "https://x/pcap.pdf"}],
        }
    ]
    run_connector(FakeConnector(notices))
    run_connector(FakeConnector(notices))  # re-scrape del mismo aviso

    with connect() as c:
        count = c.execute("SELECT COUNT(*) FROM documentos").fetchone()[0]
    assert count == 1


def test_runner_documentos_persist_failure_no_aborta_el_run(db, monkeypatch):
    """Fail-open: un fallo al persistir metadatos de documentos no debe
    impedir que licitaciones/adjudicaciones ya persistidas cuenten como éxito."""
    from db.database import connect
    from db.repositories.documentos import DocumentosRepository

    def _broken_upsert(self, licitacion_id, refs):
        raise RuntimeError("BD de documentos caída")

    monkeypatch.setattr(DocumentosRepository, "upsert_meta", _broken_upsert)

    notices = [
        {
            "id": "N1",
            "titulo": "Aviso con pliegos",
            "documentos": [{"tipo": "legal", "uri": "https://x/pcap.pdf"}],
        }
    ]
    result = run_connector(FakeConnector(notices))

    assert result.nuevas == 1  # la licitación se persistió igual
    with connect() as c:
        ids = {r[0] for r in c.execute("SELECT id_externo FROM licitaciones").fetchall()}
        n_docs = c.execute("SELECT COUNT(*) FROM documentos").fetchone()[0]
    assert ids == {"fake:N1"}
    assert n_docs == 0  # el fallo dejó los documentos sin persistir, no rompió el resto


# ---------------------------------------------------------------------------
# TED — helpers de mapeo
# ---------------------------------------------------------------------------


def test_first_lang_prefiere_spa():
    value = {"hun": ["Magyar cím"], "spa": ["Título español"], "eng": ["English title"]}
    assert _first_lang(value) == "Título español"
    assert _first_lang({"eng": ["English"]}) == "English"
    assert _first_lang({"deu": ["Deutsch"]}) == "Deutsch"
    assert _first_lang("plano") == "plano"
    assert _first_lang(None) is None


def test_nuts_provincial_ignora_pais():
    assert _nuts_provincial(["ESP", "ESP", "ES703", "ES704"]) == "ES703"
    assert _nuts_provincial(["ESP"]) is None
    assert _nuts_provincial(None) is None


# ---------------------------------------------------------------------------
# TED — parse de avisos reales (estructura validada contra la API)
# ---------------------------------------------------------------------------


def _ted_notice_cn():
    return {
        "publication-number": "371218-2026",
        "notice-type": "cn-standard",
        "notice-title": {"spa": ["España - Servicios TIC - Contratación de los servicios de CPD"]},
        "description-proc": {"spa": ["Implantación y soporte de SAP S/4HANA en el hospital"]},
        "buyer-name": {"spa": ["Servicio Andaluz de Salud"]},
        "classification-cpv": ["72000000", "72500000"],
        "publication-date": "2026-06-01+02:00",
        "deadline-receipt-tender-date-lot": ["2026-06-17+02:00"],
        "estimated-value-proc": "4562500",
        "place-of-performance": ["ESP", "ES618"],
        "contract-nature": ["services"],
        "links": {
            "pdf": {"SPA": "https://ted.europa.eu/es/notice/371218-2026/pdf"},
            "xml": {"MUL": "https://ted.europa.eu/en/notice/371218-2026/xml"},
        },
    }


def test_ted_parse_contract_notice():
    connector = TedConnector()
    parsed = connector.parse(RawNotice(natural_id="371218-2026", payload=_ted_notice_cn()))

    lic = parsed.licitacion
    assert lic.id_externo == "ted:371218-2026"
    assert lic.fuente == "ted"
    assert lic.estado == "PUB"
    assert lic.organo_contratacion == "Servicio Andaluz de Salud"
    assert lic.cpv == "72000000"
    assert lic.importe == 4562500.0
    assert lic.fecha_publicacion == "2026-06-01"
    assert lic.fecha_limite == "2026-06-17"
    assert lic.nuts_code == "ES618"
    assert lic.url == "https://ted.europa.eu/es/notice/371218-2026/pdf"
    assert "SAP" in (lic.tecnologia or "")  # detectado en la descripción
    assert parsed.adjudicaciones == []


def test_ted_parse_award_notice_crea_adjudicacion():
    notice = _ted_notice_cn()
    notice["notice-type"] = "can-standard"
    notice["winner-name"] = {"spa": ["Minsait Sistemas S.A."]}
    notice["result-value-notice"] = "3900000"

    parsed = TedConnector().parse(RawNotice(natural_id="371218-2026", payload=notice))

    assert parsed.licitacion.estado == "RES"
    assert len(parsed.adjudicaciones) == 1
    adj = parsed.adjudicaciones[0]
    assert adj.nombre == "Minsait Sistemas S.A."
    assert adj.importe_adjudicado == 3900000.0
    assert adj.licitacion_id == "ted:371218-2026"


def test_ted_parse_tipo_desconocido_descarta():
    notice = _ted_notice_cn()
    notice["notice-type"] = "brin-eeig"  # registro de entidades, no licitación
    assert TedConnector().parse(RawNotice(natural_id="X", payload=notice)) is None


def test_ted_query_y_cursor():
    connector = TedConnector(cpv_families=("48", "72"))
    q = connector._build_query("20260101")
    assert "place-of-performance IN (ESP)" in q
    assert "publication-date >= 20260101" in q
    assert "classification-cpv IN (48*)" in q and "classification-cpv IN (72*)" in q

    assert connector._since({"last_seen_updated": "2026-06-01"}) == "20260601"
    assert len(connector._since(None)) == 8  # lookback por defecto

    assert connector.new_cursor() is None  # sin fetch no avanza
