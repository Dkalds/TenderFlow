"""Tests del framework de conectores (ADR-009) y del conector TED."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta

import pytest

from scraper.connectors.base import ParsedTender, RawNotice, run_connector
from scraper.connectors.ted import TedConnector, _first_lang, _nuts_provincial, _usable_url

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
        from db.upsert import Adjudicacion, DocumentoReferencia, Licitacion, Lote

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
        # Payload separado de "ganador" (no lo toca): una lista de adjudicaciones
        # con lote_numero propio, para probar el flujo de resolución lotes->lote_id.
        for g in raw.payload.get("ganadores_multi_lote", []):
            adjs.append(
                Adjudicacion(
                    licitacion_id=lic.id_externo,
                    nombre=g["nombre"],
                    nif=g.get("nif"),
                    importe_adjudicado=g["importe_adjudicado"],
                    fecha_adjudicacion="2026-02-01",
                    lote_numero_raw=g.get("lote_numero"),
                )
            )
        docs = []
        if raw.payload.get("documentos"):
            docs = [
                DocumentoReferencia(tipo=d["tipo"], uri=d["uri"], filename=d.get("filename"))
                for d in raw.payload["documentos"]
            ]
        lotes = [
            Lote(licitacion_id=lic.id_externo, numero=lote_data["numero"])
            for lote_data in raw.payload.get("lotes", [])
        ]
        return ParsedTender(licitacion=lic, adjudicaciones=adjs, documentos=docs, lotes=lotes)

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
# Persistencia de lotes (v65_lotes) y resolución lote_numero_raw -> lote_id
# ---------------------------------------------------------------------------


def test_runner_multi_lote_misma_empresa_mismo_importe_no_pierde_filas(db):
    """Regresión del bug real: antes de v65_lotes, la unique
    (licitacion_id, nif, importe_adjudicado) descartaba en silencio una fila
    cuando la misma empresa ganaba dos lotes por el mismo importe. Con
    lote_id resuelto, ambas filas deben persistir."""
    from db.database import connect

    notices = [
        {
            "id": "N1",
            "titulo": "Expediente con dos lotes",
            "lotes": [{"numero": "1"}, {"numero": "2"}],
            "ganadores_multi_lote": [
                {
                    "nombre": "Misma Empresa SL",
                    "nif": "B00000001",
                    "importe_adjudicado": 5000.0,
                    "lote_numero": "1",
                },
                {
                    "nombre": "Misma Empresa SL",
                    "nif": "B00000001",
                    "importe_adjudicado": 5000.0,
                    "lote_numero": "2",
                },
            ],
        }
    ]
    result = run_connector(FakeConnector(notices))

    assert result.adjudicaciones == 2
    with connect() as c:
        rows = c.execute(
            "SELECT a.nif, a.importe_adjudicado, l.numero "
            "FROM adjudicaciones a JOIN lotes l ON l.id = a.lote_id "
            "WHERE a.licitacion_id = %s ORDER BY l.numero",
            ["fake:N1"],
        ).fetchall()
    assert [r[2] for r in rows] == ["1", "2"]
    assert all(r[0] == "B00000001" and r[1] == pytest.approx(5000.0) for r in rows)


def test_runner_sin_lote_preserva_dedup_antiguo(db):
    """Sin lote_numero (expediente de lote único, el caso común hoy), la
    protección original (licitacion_id, nif, importe_adjudicado) se mantiene:
    dos filas idénticas sin lote_id siguen deduplicándose a una."""
    from db.database import connect

    notices = [
        {
            "id": "N1",
            "titulo": "Expediente sin lotes",
            "ganadores_multi_lote": [
                {"nombre": "Empresa SL", "nif": "B99999999", "importe_adjudicado": 3000.0},
                {"nombre": "Empresa SL", "nif": "B99999999", "importe_adjudicado": 3000.0},
            ],
        }
    ]
    result = run_connector(FakeConnector(notices))

    assert result.adjudicaciones == 1
    with connect() as c:
        count = c.execute(
            "SELECT COUNT(*) FROM adjudicaciones WHERE licitacion_id = %s", ["fake:N1"]
        ).fetchone()[0]
    assert count == 1


def test_runner_persiste_lotes_con_metadatos(db):
    from db.database import connect

    notices = [
        {
            "id": "N1",
            "titulo": "Expediente con lotes",
            "lotes": [{"numero": "1"}, {"numero": "2"}],
        }
    ]
    run_connector(FakeConnector(notices))

    with connect() as c:
        numeros = {
            r[0]
            for r in c.execute(
                "SELECT numero FROM lotes WHERE licitacion_id = %s", ["fake:N1"]
            ).fetchall()
        }
    assert numeros == {"1", "2"}


def test_runner_lotes_reingesta_no_duplica(db):
    """replace_lotes_batch reemplaza (no acumula) en cada re-ingesta."""
    from db.database import connect

    notices = [{"id": "N1", "titulo": "Expediente", "lotes": [{"numero": "1"}]}]
    run_connector(FakeConnector(notices))
    run_connector(FakeConnector(notices))

    with connect() as c:
        count = c.execute(
            "SELECT COUNT(*) FROM lotes WHERE licitacion_id = %s", ["fake:N1"]
        ).fetchone()[0]
    assert count == 1


def test_runner_adjudicacion_sin_lote_numero_no_falla_con_lotes_presentes(db):
    """Una adjudicación sin lote_numero_raw en un expediente que sí tiene
    lotes (p.ej. una fuente que no publica la referencia) no debe romper la
    resolución: lote_id queda None, no un KeyError."""
    from db.database import connect

    notices = [
        {
            "id": "N1",
            "titulo": "Expediente mixto",
            "lotes": [{"numero": "1"}],
            "ganadores_multi_lote": [
                {"nombre": "Empresa SL", "nif": "B11111111", "importe_adjudicado": 1000.0}
            ],
        }
    ]
    result = run_connector(FakeConnector(notices))

    assert result.errores == 0
    with connect() as c:
        lote_id = c.execute(
            "SELECT lote_id FROM adjudicaciones WHERE licitacion_id = %s", ["fake:N1"]
        ).fetchone()[0]
    assert lote_id is None


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


def test_ted_url_usa_el_enlace_de_pliegos_del_comprador():
    notice = _ted_notice_cn()
    notice["document-url-lot"] = [
        "https://contrataciondelestado.es/wps/poc?uri=deeplink:detalle_licitacion"
        "&idEvl=QGM1HX7Wxp16nTs9LZ9RhQ%3D%3D"
    ]

    parsed = TedConnector().parse(RawNotice(natural_id="371218-2026", payload=notice))

    assert parsed.licitacion.url is not None
    assert "idEvl=" in parsed.licitacion.url  # el expediente, no el PDF del anuncio


def test_ted_url_prefiere_deeplink_placsp_entre_varios_lotes():
    notice = _ted_notice_cn()
    notice["document-url-lot"] = [
        "https://contractaciopublica.cat/ca/perfils-contractant/detall/12628397",
        "https://contrataciondelestado.es/wps/poc?uri=deeplink:detalle_licitacion&idEvl=abc%3D",
    ]

    parsed = TedConnector().parse(RawNotice(natural_id="371218-2026", payload=notice))

    assert parsed.licitacion.url == (
        "https://contrataciondelestado.es/wps/poc?uri=deeplink:detalle_licitacion&idEvl=abc%3D"
    )


def test_ted_url_ignora_la_raiz_de_la_plataforma():
    notice = _ted_notice_cn()
    notice["document-url-lot"] = ["https://www.contratacion.euskadi.eus"]

    parsed = TedConnector().parse(RawNotice(natural_id="371218-2026", payload=notice))

    # La home de la plataforma no acerca al pliego: mejor el PDF del anuncio.
    assert parsed.licitacion.url == "https://ted.europa.eu/es/notice/371218-2026/pdf"


def test_ted_url_cae_al_acceso_restringido_si_no_hay_publico():
    notice = _ted_notice_cn()
    notice["document-restricted-url-lot"] = [
        "https://contractaciopublica.gencat.cat/ecofin_pscp/AppJava/perfil/16138154/customProf"
    ]

    parsed = TedConnector().parse(RawNotice(natural_id="371218-2026", payload=notice))

    assert parsed.licitacion.url is not None
    assert parsed.licitacion.url.endswith("/customProf")


def test_usable_url_normaliza_y_filtra():
    # Sin esquema: ~1 de cada 10 valores llega así.
    assert _usable_url("www.contractaciopublica.cat/ca/perfils/detall/999") == (
        "https://www.contractaciopublica.cat/ca/perfils/detall/999"
    )
    # Query string basta aunque la ruta sea corta.
    assert _usable_url("https://x.es/p?id=7") == "https://x.es/p?id=7"
    # Raíces e idioma suelto: no identifican expediente ni perfil.
    assert _usable_url("https://seuelectronica.diba.cat/") is None
    assert _usable_url("https://portalcontratacion.navarra.es/es/") is None
    assert _usable_url("   ") is None


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

    # El watermark NO se consulta tal cual: se retrocede `overlap_days` (ver
    # _OVERLAP_DAYS en el conector y los tests de solapamiento más abajo).
    assert connector._since({"last_seen_updated": "2026-06-01"}) == "20260518"
    assert len(connector._since(None)) == 8  # lookback por defecto

    assert connector.new_cursor() is None  # sin fetch no avanza


# ---------------------------------------------------------------------------
# TED — solapamiento del cursor
#
# El cursor guarda el MÁXIMO `publication-date` visto. TED no termina de
# indexar el día D antes de que aparezcan avisos del día D+1, así que en cuanto
# el watermark salta a D+1 lo que quedara pendiente de D no se vuelve a
# consultar nunca. Evidencia (2026-08-16): la ingesta incremental tenía 1.307
# avisos de la ventana `publication-date >= 2026-06-10` y un backfill manual
# sobre la misma ventana insertó 362 filas nuevas (22 %).
# ---------------------------------------------------------------------------


class _FakeTedResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeTedSession:
    """API TED de mentira: aplica el `publication-date >= YYYYMMDD` de la query
    igual que la real y pagina, para que los tests midan qué avisos entran de
    verdad y no sólo cómo quedó construido el string de la query."""

    def __init__(self, notices):
        self.notices = notices
        self.queries: list[str] = []

    def post(self, url, json, timeout):
        query = json["query"]
        self.queries.append(query)
        match = re.search(r"publication-date >= (\d{4})(\d{2})(\d{2})", query)
        assert match is not None, query
        desde = "-".join(match.groups())
        vivos = [n for n in self.notices if str(n["publication-date"])[:10] >= desde]
        page, limit = json["page"], json["limit"]
        return _FakeTedResponse(
            {"notices": vivos[(page - 1) * limit : page * limit], "totalNoticeCount": len(vivos)}
        )


def _ted_aviso(pub_number: str, pub_date: str) -> dict:
    return {
        "publication-number": pub_number,
        "publication-date": f"{pub_date}+02:00",
        "notice-type": "cn-standard",
        "notice-title": {"spa": f"Aviso {pub_number}"},
    }


# El aviso que TED indexa tarde: su fecha (12-jun) es ANTERIOR al watermark que
# dejó el run previo (20-jun), así que sólo se alcanza retrocediendo.
_TARDIO = "111111-2026"
_AL_DIA = "222222-2026"


def _fetch_ids(connector, cursor):
    return [raw.natural_id for raw in connector.fetch(cursor)]


def _sesion_tardio_y_al_dia():
    return _FakeTedSession([_ted_aviso(_TARDIO, "2026-06-12"), _ted_aviso(_AL_DIA, "2026-06-20")])


def test_ted_solapamiento_recupera_avisos_indexados_tarde():
    session = _sesion_tardio_y_al_dia()
    connector = TedConnector(session=session)

    vistos = _fetch_ids(connector, {"last_seen_updated": "2026-06-20"})

    assert _TARDIO in vistos, "el solapamiento debe volver a mirar por detrás del watermark"
    assert "publication-date >= 20260606" in session.queries[0]  # 20-jun menos 14 días


def test_ted_sin_solapamiento_pierde_el_aviso_tardio():
    """Regresión del fallo original: `overlap_days=0` reproduce la estrategia
    anterior (consultar desde el watermark tal cual) y pierde el aviso."""
    connector = TedConnector(session=_sesion_tardio_y_al_dia(), overlap_days=0)

    assert _fetch_ids(connector, {"last_seen_updated": "2026-06-20"}) == [_AL_DIA]


def test_ted_solapamiento_no_retrocede_el_cursor():
    """Re-leer avisos viejos no debe hacer retroceder el watermark: `new_cursor`
    sigue siendo el máximo visto, o cada run arrastraría el cursor hacia atrás."""
    connector = TedConnector(session=_sesion_tardio_y_al_dia())

    _fetch_ids(connector, {"last_seen_updated": "2026-06-20"})

    assert connector.new_cursor() == {"last_seen_updated": "2026-06-20"}


def test_ted_solapamiento_cubre_varias_paginas():
    """El solapamiento no debe romper la paginación: el aviso tardío está en la
    segunda página de la ventana re-consultada."""
    avisos = [_ted_aviso(f"{i:06d}-2026", "2026-06-19") for i in range(100)]
    avisos.append(_ted_aviso(_TARDIO, "2026-06-12"))
    connector = TedConnector(session=_FakeTedSession(avisos))

    vistos = _fetch_ids(connector, {"last_seen_updated": "2026-06-20"})

    assert len(vistos) == 101
    assert _TARDIO in vistos


@pytest.mark.parametrize(
    "valor",
    [
        "2026-06-20",
        "2026-06-20 00:00:00+00:00",
        "20260620",
        date(2026, 6, 20),
        datetime(2026, 6, 20, 9, 30, tzinfo=UTC),
    ],
)
def test_ted_since_tolera_los_formatos_del_cursor(valor):
    """`ingestion_cursors` puede devolver str ISO, timestamp o date/datetime de
    psycopg; `--desde` además escribe el formato compacto."""
    assert TedConnector(overlap_days=5)._since({"last_seen_updated": valor}) == "20260615"


def test_ted_since_con_cursor_ilegible_cae_al_lookback():
    """Un cursor corrupto no debe tumbar el run: mejor re-escanear de más."""
    connector = TedConnector(default_lookback_days=30)
    esperado = (datetime.now(UTC).date() - timedelta(days=30)).strftime("%Y%m%d")

    assert connector._since({"last_seen_updated": "no-es-una-fecha"}) == esperado


def test_ted_desde_sigue_sobreescribiendo_since():
    """`main()` monkeypatchea `_since` para el flag `--desde`; el solapamiento
    no debe aplicarse encima de una fecha que pidió el usuario."""
    session = _FakeTedSession([_ted_aviso(_TARDIO, "2026-06-12")])
    connector = TedConnector(session=session)
    connector._since = lambda cursor: "20260101"  # exactamente lo que hace main()

    vistos = _fetch_ids(connector, {"last_seen_updated": "2026-06-20"})

    assert vistos == [_TARDIO]
    assert "publication-date >= 20260101" in session.queries[0]


# ---------------------------------------------------------------------------
# Hook post-ingesta
# ---------------------------------------------------------------------------


def test_post_ingestion_scopes_resolution_to_its_own_source():
    """Cada conector resuelve lo SUYO, acotado y con presupuesto.

    Hasta 2026-08 llamaba a `resolve_all_unlinked(fuente=source_id)` a secas:
    `fuente` sólo etiquetaba los aliases, así que ingerir 112 avisos de TED
    arrancaba un barrido del millón largo de filas pendientes de PSCP desde el
    id 0, agotaba los 10 min del step y moría antes de llegar al dedupe y a
    los eventos de contrato que corren después.
    """
    from unittest.mock import patch

    from scraper.connectors.base import _post_ingestion
    from services.entity_resolution import HOOK_TIME_BUDGET_S

    with (
        patch("services.entity_resolution.resolve_all_unlinked") as resolve_all,
        patch("services.dedupe.detect_duplicates") as dedupe,
        patch("services.contract_events.derive_new_events") as events,
        patch("shared.cache_signal.signal_cache_invalidation") as cache,
    ):
        _post_ingestion("ted")

    resolve_all.assert_called_once_with(
        fuente="ted",
        scope_fuente="ted",
        resume=True,
        time_budget_s=HOOK_TIME_BUDGET_S,
    )
    # Los pasos de detrás son justamente los que el timeout se llevaba por
    # delante: si la resolución vuelve a desbordarse, esto deja de correr.
    dedupe.assert_called_once_with(fuente="ted")
    events.assert_called_once_with()
    cache.assert_called_once_with()
