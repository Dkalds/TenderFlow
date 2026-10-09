"""Tests del conector PSCP Catalunya (Fase 5, RFC 20260611-1)."""

from __future__ import annotations

import functools
import json

import pytest
import requests

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


# ── C4.1 / D24: el conector acota al universo tecnológico ───────────────────


def _conector():
    from scraper.connectors.pscp import PscpConnector

    return PscpConnector(dataset_id="ybgg-dgi6", domain="ejemplo.cat", app_token="")


def _aviso(**campos):
    from scraper.connectors.base import RawNotice

    record = {"codi_expedient": "EXP-C4", **campos}
    return RawNotice(natural_id="EXP-C4", payload=record)


def test_descarta_el_aviso_sin_senal_tecnologica() -> None:
    """683.000 filas con 0,46 % de positivos era el corpus que ahogaba al modelo."""
    conector = _conector()
    parsed = conector.parse(_aviso(objecte_contracte="Subministrament de reactius de laboratori"))
    assert parsed is None
    assert conector.contadores_de_descarte()["pscp_sin_senal_tecnologica"] == 1


def test_conserva_el_aviso_con_senal_tecnologica() -> None:
    conector = _conector()
    parsed = conector.parse(_aviso(objecte_contracte="Manteniment de la plataforma SAP"))
    assert parsed is not None
    assert parsed.licitacion.tecnologia
    assert conector.contadores_de_descarte()["pscp_sin_senal_tecnologica"] == 0


def test_ninguna_fila_persistida_queda_sin_tecnologia() -> None:
    """El criterio de aceptación de C4.1, sobre el parser.

    «Filas nuevas de PSCP con `tecnologia IS NULL` = 0» se mide contra la BD
    tras el siguiente run; aquí se fija el invariante que lo hace cierto: sin
    CPV de TI, el parser no puede devolver una licitación sin `tecnologia`. La
    única excepción, desde el 2026-09-26, es la que trae CPV 48/72
    (`cpv_ti_universe`, ver los tests de la puerta más abajo).
    """
    conector = _conector()
    titulos = [
        "Subministrament de material d'oficina",
        "Manteniment SAP S/4HANA",
        "Servei de neteja",
        "Llicencies de programari SAP",
    ]
    persistidas = [conector.parse(_aviso(objecte_contracte=t)) for t in titulos]
    for parsed in persistidas:
        if parsed is not None:
            assert parsed.licitacion.tecnologia, (
                f"{parsed.licitacion.titulo!r} se persistiría con tecnologia NULL"
            )
    assert conector.contadores_de_descarte()["pscp_sin_senal_tecnologica"] == 2


# ── C4.4: fechas imposibles ─────────────────────────────────────────────────


def test_la_fecha_de_adjudicacion_imposible_se_descarta() -> None:
    """`1899-12-30` es el cero de la epoch de Excel: una celda vacía, no una fecha.

    Pasaba cualquier validación de formato (cuatro cifras, parsea bien) y ganaba
    el `LEAST(fecha_publicacion, fecha_adjudicacion)` que ancla el dataset de ML,
    metiendo la fila en el train de todos los folds.
    """
    conector = _conector()
    parsed = conector.parse(
        _aviso(
            objecte_contracte="Manteniment SAP",
            data_publicacio_anunci="2026-03-01T00:00:00.000",
            denominacio_adjudicatari="Empresa SL",
            data_adjudicacio_contracte="1899-12-30T00:00:00.000",
        )
    )
    assert parsed is not None
    assert parsed.adjudicaciones
    # Cae al respaldo (la publicación), que es lo que ya hacía con el campo vacío.
    assert parsed.adjudicaciones[0].fecha_adjudicacion == "2026-03-01"
    assert conector.contadores_de_descarte()["pscp_fechas_implausibles"] == 1


def test_la_fecha_de_adjudicacion_plausible_se_conserva() -> None:
    conector = _conector()
    parsed = conector.parse(
        _aviso(
            objecte_contracte="Manteniment SAP",
            data_publicacio_anunci="2026-03-01T00:00:00.000",
            denominacio_adjudicatari="Empresa SL",
            data_adjudicacio_contracte="2026-05-20T00:00:00.000",
        )
    )
    assert parsed is not None
    assert parsed.adjudicaciones[0].fecha_adjudicacion == "2026-05-20"
    assert conector.contadores_de_descarte()["pscp_fechas_implausibles"] == 0


def test_los_contadores_llegan_al_resumen_del_run() -> None:
    """`descartadas` no distingue el acotado deliberado de un parser roto."""
    from scraper.connectors.base import ConnectorRunResult

    resultado = ConnectorRunResult(source_id="pscp", fetched=10, parsed=2, descartadas=8)
    resultado.detalles.update(_conector().contadores_de_descarte())
    resumen = resultado.as_dict()
    assert resumen["descartadas"] == 8
    assert "pscp_sin_senal_tecnologica" in resumen
    assert "pscp_keyword_ambigua_sin_cpv_ti" in resumen
    assert "pscp_fechas_implausibles" in resumen


# ── Puerta endurecida (2026-09-26): keywords ambiguas y apóstrofos ──────────
#
# Cada caso es un título real de producción que el filtro de keywords a secas
# admitía (o, en los de apóstrofo, rechazaba) con el CPV con el que llegó.

_FALSOS_POSITIVOS_REALES = [
    (
        "Contracte del servei de manteniment correctiu i preventiu dels ascensors",
        "50750000-7",
    ),
    ("COMPRA DE MATERIAL DE FERRETERIA PER A LA GERÈCNIA APICCC. CODI SAP 7107067", "44316000-8"),
    ("SAP 30053588 MAQUINETA RASURAT 2 FULLA N/ESTÈRIL 1 ÚS", "33140000-3"),
    ("CABLE APPLE LIGHTNING USB-A 1m BLANC", "32000000-3"),
    # CPV de material informático (302): la corroboración es 48/72, no «algo
    # informático», precisamente por esto.
    ("Nou Apartat | Apple USB-C to Lightning Cable (1M) | Gastos de envio", "30230000-0"),
    (
        "Subministrament i instal·lació d'un teló (cortina) tallafocs tèxtil",
        "44480000-8||45343000-3",
    ),
    ("Subministrament a doll de PACS per al tractament de potabilització", "24312123-2"),
    ("api 20 enterobacterias.", "33696500-0"),
    ("Subministrament i posada en servei de bateries per ampliar el SAI del CPD", "31440000-2"),
    ("Subministrament de dos portasignatures corporatius per l'ICF", "30197000-6"),
]


@pytest.mark.parametrize(("titulo", "cpv"), _FALSOS_POSITIVOS_REALES)
def test_la_keyword_ambigua_con_cpv_ajeno_a_ti_no_entra(titulo: str, cpv: str) -> None:
    from scraper.connectors.pscp import MOTIVO_AMBIGUA_SIN_CPV_TI, senal_tecnologica

    senal = senal_tecnologica(titulo, cpv)
    assert not senal.admitida
    assert senal.motivo == MOTIVO_AMBIGUA_SIN_CPV_TI


@pytest.mark.parametrize(
    ("titulo", "cpv"),
    [
        # La misma keyword ambigua, corroborada por un CPV 48/72 en cualquier
        # posición de la lista.
        ("Servei manteniment mòduls Finances SAP", "72265000-0"),
        ("Manteniment correctiu i evolutiu de l'aplicatiu d'inscripcions", "72212000-4"),
        (
            "Subministrament de quatre tallafocs de nova generació FortiGate",
            "30200000-1||30237130-9||48900000-7",
        ),
        # Sin CPV no hay contradicción: conserva el beneficio de la duda.
        ("Manteniment SAP", None),
        # Una keyword no ambigua basta aunque el CPV sea absurdo (licencias de
        # Office codificadas como obra de puentes, real).
        ("renovació de subscripcions a Microsoft Office 365", "45221119-9"),
        # `hana` no es ambigua: arrastra a `sap` con ella.
        ("Renovació emmagatzematge SAP HANA 2025", "30233180-6"),
    ],
)
def test_la_senal_legitima_sigue_entrando(titulo: str, cpv: str | None) -> None:
    from scraper.connectors.pscp import senal_tecnologica

    senal = senal_tecnologica(titulo, cpv)
    assert senal.admitida, senal
    assert senal.tecnologias
    assert senal.keywords


def test_el_apostrofo_tipografico_ya_no_esconde_la_keyword() -> None:
    """El apóstrofo curvo (U+2019) es como escribe la PSCP; el diccionario usa el recto."""
    from scraper.connectors.pscp import senal_tecnologica

    senal = senal_tecnologica("Servei de desenvolupament d\u2019aplicacions", "79000000-4")
    assert senal.admitida
    assert "DESARROLLO" in senal.tecnologias
    assert "desenvolupament d'aplicacions" in senal.keywords


def test_el_conector_cuenta_el_descarte_por_keyword_ambigua() -> None:
    conector = _conector()
    parsed = conector.parse(
        _aviso(objecte_contracte="CABLE APPLE LIGHTNING USB-A 1m", codi_cpv="32000000-3")
    )
    assert parsed is None
    contadores = conector.contadores_de_descarte()
    assert contadores["pscp_keyword_ambigua_sin_cpv_ti"] == 1
    assert contadores["pscp_sin_senal_tecnologica"] == 0


def test_el_conector_corrobora_con_cualquier_cpv_de_la_lista() -> None:
    """Se guarda el primer CPV, pero la puerta mira todos: el orden no decide."""
    conector = _conector()
    parsed = conector.parse(
        _aviso(objecte_contracte="Manteniment SAP", codi_cpv="50000000-5||72267000-4")
    )
    assert parsed is not None
    assert parsed.licitacion.tecnologia == "SAP"


@pytest.mark.parametrize(
    ("titulo", "cpv"),
    [
        # Casos reales que el dry-run de la purga del 2026-09-26 iba a borrar:
        # la keyword es ambigua, pero el CPV es de equipo informático o de su
        # mantenimiento.
        ("Ampliació Cabina Backup del CPD de Cerdanyola", "30200000-1"),
        (
            "Manteniment equipament hardware del CPD de l'ajuntament Barcelona",
            "50312610-4",
        ),
    ],
)
def test_el_equipo_informatico_corrobora_una_keyword_ambigua(titulo: str, cpv: str) -> None:
    from scraper.connectors.pscp import MOTIVO_ADMITIDA, senal_tecnologica

    senal = senal_tecnologica(titulo, cpv)
    assert senal.motivo == MOTIVO_ADMITIDA
    assert "CLOUD_INFRA" in senal.tecnologias


def test_sap_no_se_corrobora_con_material_informatico() -> None:
    """El ICS compra ordenadores con su «CODI SAP»: para `sap` solo vale 48/72."""
    from scraper.connectors.pscp import MOTIVO_AMBIGUA_SIN_CPV_TI, senal_tecnologica

    senal = senal_tecnologica("ORDINADOR PORTÀTIL CODI SAP 7104412", "30213100-6")
    assert senal.motivo == MOTIVO_AMBIGUA_SIN_CPV_TI


@pytest.mark.parametrize(
    ("titulo", "cpv"),
    [
        # Reales, del mismo dry-run: TI por CPV que no casa con el diccionario.
        ("Business starter anual i google workspace", "48218000-9"),
        ("Programari factorial de l'1 de març a 1 d'abril", "48900000-7"),
        ("MANTENIMENT LLIC XEN ORCHESTRA", "72267000-4"),
        # El 48/72 puede no ir primero en la lista.
        ("Renovació anual", "30200000-1||72267000-4"),
    ],
)
def test_sin_keyword_entra_por_cpv_ti_y_sin_etiquetas(titulo: str, cpv: str) -> None:
    from scraper.connectors.pscp import MOTIVO_CPV_TI, senal_tecnologica

    senal = senal_tecnologica(titulo, cpv)
    assert senal.admitida
    assert senal.motivo == MOTIVO_CPV_TI
    assert senal.tecnologias == ()
    assert senal.keywords == ()


@pytest.mark.parametrize(
    "cpv",
    [None, "90910000-9", "30213100-6"],  # sin CPV, limpieza, un portátil
)
def test_sin_keyword_ni_cpv_48_72_no_entra(cpv: str | None) -> None:
    from scraper.connectors.pscp import MOTIVO_SIN_SENAL, senal_tecnologica

    assert senal_tecnologica("Subministrament diversos", cpv).motivo == MOTIVO_SIN_SENAL


def test_el_conector_persiste_lo_de_cpv_ti_como_en_placsp() -> None:
    """Sin `tecnologia` y con el `inclusion_reason` de PLACSP: fuera del Radar."""
    conector = _conector()
    parsed = conector.parse(
        _aviso(objecte_contracte="Llicències Google Workspace", codi_cpv="48218000-9")
    )
    assert parsed is not None
    assert parsed.licitacion.tecnologia is None
    assert parsed.licitacion.raw_keywords is None
    assert parsed.licitacion.inclusion_reason == "cpv_ti_universe"
    assert parsed.licitacion.analysis_universe == "pscp_observed"
    assert conector.contadores_de_descarte()["pscp_sin_senal_tecnologica"] == 0


def test_cada_keyword_ambigua_existe_en_la_semilla() -> None:
    """Una keyword renombrada en el diccionario dejaría aquí una entrada muerta."""
    from config.keywords import TECHNOLOGY_KEYWORDS
    from scraper.connectors.pscp import KEYWORDS_AMBIGUAS

    semilla = {kw.casefold() for kws in TECHNOLOGY_KEYWORDS.values() for kw in kws}
    assert not KEYWORDS_AMBIGUAS - semilla


# ── Reintento por página (issue #408) ───────────────────────────────────────
#
# La petición de página no tenía reintento a ningún nivel. El 2026-09-27 la
# reingesta completa de `purga-pscp.yml` murió a los 55 minutos y 812.591 avisos
# por UN «Read timed out» de Socrata, y en los dos días siguientes la pasada
# diaria cayó tres veces más por lo mismo, tapada por su `continue-on-error`.

#: El mensaje literal del issue: el de urllib3, que `requests` no retoca.
_READ_TIMEOUT = (
    "HTTPSConnectionPool(host='analisi.transparenciacatalunya.cat', port=443): "
    "Read timed out. (read timeout=60)"
)
#: La republicación completa del dataset dejó ~1,8 M de filas con esta misma
#: marca: el recorrido avanza por `:id`, que es donde un reintento mal hecho
#: perdería o repetiría filas.
_MARCA = "2026-07-13T13:26:08.273Z"


def _fila(expediente: str) -> dict:
    """Una fila que pasa la puerta, con la marca y el id que ordenan el recorrido."""
    return dict(
        _pscp_record(),
        codi_expedient=expediente,
        **{":updated_at": _MARCA, ":id": f"row-{expediente.lower()}"},
    )


def _cursor_en(expediente: str) -> dict:
    return {"last_seen_updated": _MARCA, "last_entry_id": f"row-{expediente.lower()}"}


def _respuesta(status: int, filas: list | None = None) -> requests.Response:
    """Un ``requests.Response`` de verdad sobre un cuerpo enlatado.

    Su ``raise_for_status`` y su ``json`` son los reales: lo que se clasifica
    como transitorio es el ``HTTPError`` que produce ``requests``, no uno
    fabricado aquí con la forma que le convenga al test.
    """
    respuesta = requests.Response()
    respuesta.status_code = status
    respuesta.url = "https://ejemplo.cat/resource/abcd-1234.json"
    respuesta._content = json.dumps(filas or []).encode()
    return respuesta


class _SesionConGuion:
    """Contesta cada petición con el siguiente paso del guion.

    Un paso es una página (lista de filas), un estado HTTP o la excepción con
    la que ``requests`` se queda sin respuesta. Agotado el guion contesta
    ``siempre``; sin él, una petición de más es un fallo del test.
    """

    def __init__(self, *guion, siempre=None):
        self._guion = guion
        self._siempre = siempre
        self.calls: list[dict] = []

    def get(self, url, *, params, headers, timeout):
        n = len(self.calls)
        self.calls.append(params)
        if n < len(self._guion):
            paso = self._guion[n]
        elif self._siempre is not None:
            paso = self._siempre
        else:
            raise AssertionError(f"petición {n + 1} fuera del guion: {params['$where']}")
        if isinstance(paso, BaseException):
            raise paso
        if isinstance(paso, int):
            return _respuesta(paso)
        return _respuesta(200, paso)


@pytest.fixture()
def esperas(monkeypatch):
    """Páginas de dos filas y ninguna espera real; devuelve las que se habrían dormido.

    tenacity duerme entre intentos con el ``sleep`` del decorador (mismo parche
    que la fixture ``circuito`` de ``tests/test_document_fetcher.py``): sin
    anularlo, el caso que agota los intentos tardaría sus ~17 s de verdad.
    """
    from scraper.connectors import pscp

    dormidas: list[float] = []
    monkeypatch.setattr(pscp._pedir_pagina.retry, "sleep", dormidas.append)
    monkeypatch.setattr(pscp, "_PAGE_SIZE", 2)
    monkeypatch.setattr(pscp, "_PAGE_PAUSE_S", 0)
    return dormidas


_TROPIEZOS = [
    pytest.param(requests.ReadTimeout(_READ_TIMEOUT), id="read-timeout"),
    pytest.param(requests.ConnectTimeout("Connection to host timed out."), id="connect-timeout"),
    pytest.param(requests.ConnectionError("Connection aborted."), id="conexion"),
    pytest.param(
        requests.exceptions.ChunkedEncodingError(
            "Connection broken: IncompleteRead(8192 bytes read, 11817 more expected)"
        ),
        id="cuerpo-cortado",
    ),
    pytest.param(429, id="429"),
    pytest.param(500, id="500"),
    pytest.param(502, id="502"),
    pytest.param(503, id="503"),
    pytest.param(504, id="504"),
]


@pytest.mark.parametrize("tropiezo", _TROPIEZOS)
def test_un_tropiezo_en_una_pagina_se_reintenta_sin_perder_ni_repetir_avisos(esperas, tropiezo):
    """El caso del issue: la segunda página falla una vez y al reintento responde."""
    sesion = _SesionConGuion(
        [_fila("A"), _fila("B")],
        tropiezo,
        [_fila("C"), _fila("D")],
        [_fila("E")],
    )
    conector = PscpConnector(dataset_id="abcd-1234", session=sesion)

    avisos = [n.natural_id for n in conector.fetch({"last_seen_updated": "2026-07-13"})]

    assert avisos == ["A", "B", "C", "D", "E"]
    # El reintento pide la MISMA página: la paginación es por cursor y el cursor
    # no se mueve hasta que la página se ha servido entera.
    assert len(sesion.calls) == 4
    assert sesion.calls[2] == sesion.calls[1]
    assert ":id > 'row-b'" in sesion.calls[1]["$where"]
    assert ":id > 'row-d'" in sesion.calls[3]["$where"]
    assert conector.new_cursor() == _cursor_en("E")
    assert len(esperas) == 1


def test_un_fallo_que_no_cede_agota_los_intentos_y_sale_el_error_original(esperas):
    caida = requests.ReadTimeout(_READ_TIMEOUT)
    sesion = _SesionConGuion([_fila("A"), _fila("B")], siempre=caida)
    conector = PscpConnector(dataset_id="abcd-1234", session=sesion)

    vistos = []
    with pytest.raises(requests.ReadTimeout) as fallo:
        for aviso in conector.fetch({"last_seen_updated": "2026-07-13"}):
            vistos.append(aviso.natural_id)

    # El error de siempre y no un ``RetryError`` que lo envuelva: ``run_connector``
    # lo registra con ``str(e)``, y ese texto es por el que se reconoce el fallo.
    assert fallo.value is caida
    assert len(sesion.calls) == 1 + 4
    # Lo servido antes de la caída ya salió, y el cursor se queda en ello.
    assert vistos == ["A", "B"]
    assert conector.new_cursor() == _cursor_en("B")


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_un_4xx_que_no_pide_esperar_se_pide_una_sola_vez(esperas, status):
    """Socrata contesta 400 a un SoQL mal formado: repetirlo da lo mismo."""
    sesion = _SesionConGuion(siempre=status)
    conector = PscpConnector(dataset_id="abcd-1234", session=sesion)

    with pytest.raises(requests.HTTPError) as fallo:
        list(conector.fetch(None))

    assert fallo.value.response.status_code == status
    assert len(sesion.calls) == 1
    assert esperas == []


def test_los_intentos_y_las_esperas_son_los_del_reintento_compartido(esperas):
    """Cuatro intentos y tres esperas crecientes: el ``http_retry`` de todo el scraper."""
    sesion = _SesionConGuion(siempre=503)
    conector = PscpConnector(dataset_id="abcd-1234", session=sesion)

    with pytest.raises(requests.HTTPError) as fallo:
        list(conector.fetch(None))

    assert fallo.value.response.status_code == 503
    assert len(sesion.calls) == 4
    # 2, 4 y 8 s, cada una con hasta 2 s de jitter. El tope de 30 s no llega a
    # tocarse con cuatro intentos: una página caída cuesta como mucho 20 s de
    # espera, más lo que tarde en fallar cada petición.
    assert len(esperas) == 3
    for espera, base in zip(esperas, (2, 4, 8), strict=True):
        assert base <= espera <= base + 2


def test_un_cuerpo_que_siempre_se_corta_acaba_en_error_de_conexion(esperas):
    """``requests`` no da el corte a medio cuerpo como ``ConnectionError``; el conector sí."""
    corte = requests.exceptions.ChunkedEncodingError(
        "Connection broken: IncompleteRead(8192 bytes read, 11817 more expected)"
    )
    sesion = _SesionConGuion(siempre=corte)
    conector = PscpConnector(dataset_id="abcd-1234", session=sesion)

    with pytest.raises(requests.ConnectionError) as fallo:
        list(conector.fetch(None))

    assert fallo.value.__cause__ is corte
    assert "IncompleteRead" in str(fallo.value)
    assert len(sesion.calls) == 4


class _Pasada:
    """``main()`` sobre una sesión dada, y lo que habría escrito en Postgres."""

    def __init__(self, monkeypatch) -> None:
        self._monkeypatch = monkeypatch
        self.lotes: list[list[str]] = []
        self.cursores: list[dict] = []
        self.fallos: list[tuple[str, str]] = []

    def ejecutar(self, sesion) -> int:
        """La invocación de ``purga-pscp.yml``: ``python -m scraper.connectors.pscp --desde …``."""
        from scraper.connectors import pscp

        self._monkeypatch.setattr(
            pscp, "PscpConnector", lambda **kw: PscpConnector(session=sesion, **kw)
        )
        return pscp.main(["--desde", "2000-01-01", "--dataset", "abcd-1234"])


@pytest.fixture()
def pasada(monkeypatch, esperas):
    """``main()`` de punta a punta sin Postgres.

    Los dobles de ``runner_sin_bd`` (``tests/test_documentos_plataforma.py``)
    más los de la escritura, porque aquí la pasada sí trae filas. El runner es
    el de verdad, con lotes de tres: con páginas de dos, un fallo en la tercera
    página pilla un aviso en memoria, que es el caso que interesa mirar.
    """
    import db.database as database
    from db.upsert import UpsertResult
    from scraper.connectors import base

    escrito = _Pasada(monkeypatch)

    def upsert(licitaciones, *, source):
        ids = [lic.id_externo for lic in licitaciones]
        escrito.lotes.append(ids)
        return UpsertResult(inserted=ids, modified=[], unchanged=[])

    monkeypatch.setattr(database, "init_db", lambda: None)
    monkeypatch.setattr(database, "close_pool", lambda: None)
    monkeypatch.setattr(base, "get_cursor", lambda source_id: None)
    monkeypatch.setattr(base, "set_cursor", lambda source_id, **c: escrito.cursores.append(c))
    monkeypatch.setattr(base, "upsert_licitaciones_with_history", upsert)
    monkeypatch.setattr(
        base,
        "record_failure",
        lambda run_id, fuente, exc, **k: escrito.fallos.append((k["scope"], str(exc))),
    )
    monkeypatch.setattr(base, "record_source_started", lambda source_id: None)
    monkeypatch.setattr(base, "_record_source_completed", lambda result: None)
    monkeypatch.setattr(base, "_post_ingestion", lambda *a, **k: None)
    monkeypatch.setattr(base, "run_connector", functools.partial(base.run_connector, batch_size=3))
    return escrito


def test_la_pasada_con_un_timeout_puntual_termina_bien_y_escribe_cada_aviso_una_vez(pasada):
    sesion = _SesionConGuion(
        [_fila("A"), _fila("B")],
        requests.ReadTimeout(_READ_TIMEOUT),
        [_fila("C"), _fila("D")],
        [_fila("E")],
    )

    assert pasada.ejecutar(sesion) == 0

    escritos = [id_externo for lote in pasada.lotes for id_externo in lote]
    assert escritos == ["pscp:A", "pscp:B", "pscp:C", "pscp:D", "pscp:E"]
    assert pasada.fallos == []
    assert pasada.cursores[-1] == _cursor_en("E")


def test_la_pasada_con_la_fuente_caida_sigue_fallando_y_conserva_lo_ya_escrito(pasada):
    """Lo que el reintento no cambia: un fallo real no sale en verde.

    Y lo que ya pasaba y conviene tener escrito: el cursor avanza con cada lote
    (``cursor_advances_incrementally``), así que la pasada cortada no pierde lo
    escrito, y el aviso que estaba en memoria se vuelve a pedir en la siguiente
    porque el cursor se quedó antes que él.
    """
    sesion = _SesionConGuion(
        [_fila("A"), _fila("B")],
        [_fila("C"), _fila("D")],
        siempre=requests.ReadTimeout(_READ_TIMEOUT),
    )

    assert pasada.ejecutar(sesion) == 1

    assert len(sesion.calls) == 2 + 4
    assert pasada.fallos == [("fetch", _READ_TIMEOUT)]
    assert pasada.lotes == [["pscp:A", "pscp:B", "pscp:C"]]
    assert pasada.cursores == [_cursor_en("C")]
