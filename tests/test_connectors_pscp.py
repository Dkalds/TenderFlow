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
    # Fase desconocida: se conserva entera, plegada y en mayúsculas
    assert _fase_to_estado("Fase rara") == "FASE RARA"


def test_fase_to_estado_mapea_las_fases_sin_equivalente_placsp():
    """Las seis fases PSCP que se guardaban como etiqueta catalana en crudo.

    Son las que llenaron la columna en producción (ver la migración v91): 645k
    filas en ``PUBLICACIÓ AGREGADA`` sólo porque nadie las había mapeado.
    """
    assert _fase_to_estado("Publicació agregada de contractes menors") == "AGR"
    assert _fase_to_estado("Execució") == "EJEC"
    assert _fase_to_estado("Expedient en avaluació") == "EV"
    assert _fase_to_estado("Alerta futura") == "PRE"
    assert _fase_to_estado("Consulta preliminar del mercat") == "CPM"
    assert _fase_to_estado("Eva") == "EV"


def test_fase_to_estado_no_trunca_ni_deja_espacios():
    """El ``[:20]`` de la ingesta era el origen de los estados mutilados.

    ``'PUBLICACIÓ AGREGADA '`` —con espacio final— y ``'EXPEDIENT EN AVALUAC'``
    no venían así de la fuente: eran el corte cayendo a mitad de palabra. Aquí
    se fija que ninguna fase larga vuelva a producir un código inventado.
    """
    largo = _fase_to_estado("Fase larguísima que no reconoce nadie todavía")
    assert largo == "FASE LARGUISIMA QUE NO RECONOCE NADIE TODAVIA"
    assert largo is not None and largo == largo.strip()


def test_fase_to_estado_reconoce_el_valor_ya_truncado():
    """Migración e ingesta tienen que coincidir sobre el dato mutilado.

    v91 normaliza lo que ya está en la BD, y ahí ``EXPEDIENT EN AVALUAC`` está
    cortado justo antes de la ``i`` de ``avaluació``. Si el prefijo de Python
    fuera ``avaluaci`` y el de SQL ``avaluac``, las dos rutas discreparían.
    """
    assert _fase_to_estado("EXPEDIENT EN AVALUAC") == "EV"
    assert _fase_to_estado("PUBLICACIÓ AGREGADA ") == "AGR"


def test_fase_to_estado_lo_especifico_gana_a_lo_generico():
    """Una publicación agregada de adjudicaciones es AGR, no ADJ.

    El orden de ``_FASE_ESTADO`` es la única cosa que lo garantiza: ambas
    subcadenas están presentes en la misma fase.
    """
    assert _fase_to_estado("Publicació agregada d'adjudicacions") == "AGR"


def test_field_candidates_y_number():
    record = {"pressupost_licitacio_amb": "1512500.61"}  # solo segundo candidato
    assert _field(record, "importe") == "1512500.61"
    assert _number({"pressupost_licitacio_sense": "1250000.50"}, "importe") == 1250000.50
    assert _number({"pressupost_licitacio_sense": "n/d"}, "importe") is None


def test_pscp_since_devuelve_cursor_sin_solape():
    """Desde el fix del 2026-07-12: sin solape de día -- last_entry_id
    (usado en fetch()) da la continuidad exacta, así que _since() propaga
    el timestamp del cursor tal cual, completo (no solo la fecha)."""
    connector = PscpConnector(dataset_id="t-t")
    assert connector._since({"last_seen_updated": "2026-06-10T08:00:00.000"}) == (
        "2026-06-10T08:00:00.000"
    )
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

    rec1 = dict(_pscp_record(), **{":updated_at": "2026-05-21T08:00:00.000Z", ":id": "row-1"})
    rec2 = dict(
        _pscp_record(),
        codi_expedient="X-2",
        **{":updated_at": "2026-05-22T09:00:00.000Z", ":id": "row-2"},
    )
    session = FakeSession(pages=[[rec1, rec2]])
    connector = PscpConnector(dataset_id="abcd-1234", session=session)

    notices = list(connector.fetch({"last_seen_updated": "2026-05-21"}))

    assert [n.natural_id for n in notices] == ["CTTI-2026-00123", "X-2"]
    # Cursor completo (timestamp + id), NO truncado a fecha (fix 2026-07-12).
    assert connector.new_cursor() == {
        "last_seen_updated": "2026-05-22T09:00:00.000Z",
        "last_entry_id": "row-2",
    }
    where = session.calls[0]["$where"]
    # Sin solape de día: el cursor de entrada no traía last_entry_id, así
    # que arranca con '>=' simple desde el valor exacto del cursor.
    assert ":updated_at >= '2026-05-21'" in where
    # Socrata rechaza con 400 "$select=:updated_at, *" (campo de sistema antes
    # del wildcard) — el wildcard debe ir primero. :id es el desempate estable
    # de la paginación por cursor (evita $offset, que degrada ~O(offset)).
    assert session.calls[0]["$select"] == "*, :updated_at, :id"


def test_pscp_fetch_pagina_multiple_usa_cursor_no_offset(monkeypatch):
    """La página 2+ no usa $offset -- pagina por (:updated_at, :id).

    Medido en vivo contra el dataset real: $offset=1000 tarda ~5 minutos
    (Socrata recorre y descarta todas las filas anteriores) contra ~2s con
    cursor. Ver comentario en PscpConnector.fetch.
    """
    monkeypatch.setattr("scraper.connectors.pscp._PAGE_SIZE", 2)
    monkeypatch.setattr("scraper.connectors.pscp._PAGE_PAUSE_S", 0)

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
            page = self.pages[len(self.calls) - 1]
            return FakeResponse(page)

    # Página 1: 2 filas (= _PAGE_SIZE) -> dispara página 2. Página 2: 1 fila
    # (< _PAGE_SIZE) -> corta el loop.
    rec1 = dict(_pscp_record(), **{":updated_at": "2026-05-21T08:00:00.000Z", ":id": "row-a"})
    rec2 = dict(
        _pscp_record(),
        codi_expedient="X-2",
        **{":updated_at": "2026-05-21T08:00:00.000Z", ":id": "row-b"},
    )
    rec3 = dict(
        _pscp_record(),
        codi_expedient="X-3",
        **{":updated_at": "2026-05-22T09:00:00.000Z", ":id": "row-c"},
    )
    session = FakeSession(pages=[[rec1, rec2], [rec3]])
    connector = PscpConnector(dataset_id="abcd-1234", session=session)

    notices = list(connector.fetch({"last_seen_updated": "2026-05-21"}))

    assert [n.natural_id for n in notices] == ["CTTI-2026-00123", "X-2", "X-3"]
    assert len(session.calls) == 2
    for call in session.calls:
        assert "$offset" not in call
    where_page2 = session.calls[1]["$where"]
    # Desempate: misma marca de tiempo que rec1/rec2, id > 'row-b' (el
    # último visto en la página 1) -- sin esto, filas con timestamp idéntico
    # (frecuente tras una republicación completa del dataset) se perderían.
    assert ":updated_at = '2026-05-21T08:00:00.000Z'" in where_page2
    assert ":id > 'row-b'" in where_page2


def test_pscp_cursor_avanza_entre_runs_con_timestamps_repetidos(monkeypatch):
    """Regresión del bug real detectado en producción (2026-07-12): una
    republicación masiva del dataset deja millones de filas con el MISMO
    ``:updated_at``. Sin persistir ``last_entry_id`` entre corridas, cada
    run reconsulta desde el mismo punto y el cursor queda pegado para
    siempre (confirmado en logs de Actions: 6+ runs con
    ``last_seen_updated='2026-06-19'`` sin avanzar un solo segundo).

    Este test simula DOS runs separados (dos instancias de connector, cursor
    persistido entre ambas) sobre filas que comparten exactamente el mismo
    ``:updated_at`` y verifica que el segundo run avanza más allá de las
    filas ya vistas por el primero -- no las repite ni se congela.
    """
    monkeypatch.setattr("scraper.connectors.pscp._PAGE_PAUSE_S", 0)

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

    # Las 3 filas comparten el mismo :updated_at (republicación masiva).
    same_stamp = "2026-06-19T00:00:00.000Z"
    rec_a = dict(_pscp_record(), codi_expedient="A", **{":updated_at": same_stamp, ":id": "id-a"})
    rec_b = dict(_pscp_record(), codi_expedient="B", **{":updated_at": same_stamp, ":id": "id-b"})
    rec_c = dict(_pscp_record(), codi_expedient="C", **{":updated_at": same_stamp, ":id": "id-c"})

    # ── Run 1: sin cursor previo -- ve A y B, timeoutea (simulado: solo 1 página) ──
    session1 = FakeSession(pages=[[rec_a, rec_b]])
    connector1 = PscpConnector(dataset_id="abcd-1234", session=session1)
    notices1 = list(connector1.fetch({"last_seen_updated": "2026-06-19"}))
    assert [n.natural_id for n in notices1] == ["A", "B"]
    cursor_after_run1 = connector1.new_cursor()
    assert cursor_after_run1 == {"last_seen_updated": same_stamp, "last_entry_id": "id-b"}

    # ── Run 2: retoma con el cursor persistido -- debe pedir solo lo nuevo (C) ──
    session2 = FakeSession(pages=[[rec_c]])
    connector2 = PscpConnector(dataset_id="abcd-1234", session=session2)
    notices2 = list(connector2.fetch(cursor_after_run1))

    where_run2 = session2.calls[0]["$where"]
    # Con el bug viejo, esto habría sido ":updated_at >= '2026-06-19'" --
    # idéntico al run 1, re-pidiendo A y B para siempre.
    assert f":updated_at = '{same_stamp}'" in where_run2
    assert ":id > 'id-b'" in where_run2
    assert [n.natural_id for n in notices2] == ["C"]
