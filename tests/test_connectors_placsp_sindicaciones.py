"""Conectores de las sindicaciones 1143 (contratos menores) y 1044 (agregadas) de PLACSP.

Los dos están **apagados por defecto** (decisión del dueño, revisión de D16):
sin su variable de URL declaran ``disabled`` y no descargan nada. Lo que fija
este fichero:

- Contratos menores: entran filtrados por la misma puerta tecnológica que
  PLACSP, pero **nunca como licitación abierta** —cerrados, sin plazo, fuera
  del universo que alimenta Radar, listado, superficie pública, KPIs y ML— y
  sí con sus adjudicaciones, que es para lo que sirven.
- Contratos menores: la clave lleva el órgano, porque el número de expediente de
  un menor lo repiten órganos distintos (medido contra el feed real).
- Agregadas: entran como oportunidades del universo tecnológico, con su
  namespace, y el dedupe las marca cuando el contrato ya entra por otra fuente.

Las fixtures son recortes reales de los feeds, bajados el 2026-10-24 (ver
``tests/fixtures/placsp_sindicaciones/README.md``). Los ``test_integration_*``
corren contra Postgres.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from lxml import etree

from scraper.connectors import FUERA_DE_ALCANCE, REGISTERED_SOURCES_BY_ID
from scraper.connectors import placsp_agregadas as agregadas
from scraper.connectors import placsp_menores as menores
from scraper.connectors.base import RawNotice

_FIXTURES = Path(__file__).parent / "fixtures" / "placsp_sindicaciones"
_ATOM_NS = "{http://www.w3.org/2005/Atom}"
_NS = {
    "cac": "urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2",
    "cacext": "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2",
    "cbcext": "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2",
}
_IDS_ORGANO = (
    "./cacext:ContractFolderStatus/cacext:LocatedContractingParty/cac:Party/cac:PartyIdentification"
)


def _entries(nombre: str) -> list[tuple[Any, str]]:
    raiz = etree.fromstring((_FIXTURES / nombre).read_bytes())
    return [
        (entry, entry.findtext(f"{_ATOM_NS}updated") or "")
        for entry in raiz.findall(f"{_ATOM_NS}entry")
    ]


def _raw(entry: Any, updated: str) -> RawNotice:
    return RawNotice(natural_id=updated, payload=(entry, updated))


@pytest.fixture()
def feed(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """``iter_live_entries`` servido desde la fixture que diga ``feed['fichero']``."""
    estado: dict[str, Any] = {"fichero": None, "llamadas": []}

    def iter_live_entries(**kw: Any) -> tuple[list[tuple[Any, str]], dict[str, Any]]:
        estado["llamadas"].append(kw)
        entries = _entries(estado["fichero"])
        meta = {
            "newest_updated": max(u for _, u in entries),
            "etag": '"e1"',
            "last_modified": None,
        }
        return entries, meta

    monkeypatch.setattr("scraper.atom_live.iter_live_entries", iter_live_entries)
    return estado


# ── Contratos menores: el modelado ───────────────────────────────────────────

# Entradas de contratos_menores_1143.atom, por posición: 0 desarrollo evolutivo
# (keyword), 1 suscripción Gartner (CPV 72), 2 mantenimiento de Madrid (CPV 72,
# adjudicataria con NIF enmascarado), 3 ortoprótesis (sin señal) y 4-5 dos órganos
# distintos con el mismo ContractFolderID «1/2026» (sin señal).
_ORGANO_PROMETEO = "11778670221627"
_ID_PROMETEO = f"placsp_menores:{_ORGANO_PROMETEO}:2026/SP03032007/00000540E"
_CPV_TI = "72000000"


def _menores_parseados() -> tuple[menores.PlacspContratosMenoresConnector, list[Any]]:
    conector = menores.PlacspContratosMenoresConnector(menores.URL_SINDICACION_1143)
    return conector, [
        conector.parse(_raw(e, u)) for e, u in _entries("contratos_menores_1143.atom")
    ]


def _entrada_menor(posicion: int) -> tuple[Any, str]:
    return _entries("contratos_menores_1143.atom")[posicion]


def test_un_contrato_menor_entra_cerrado_sin_plazo_y_fuera_del_universo_de_licitaciones():
    _, parseados = _menores_parseados()
    parsed = parseados[0]
    assert parsed is not None
    lic = parsed.licitacion

    assert lic.id_externo == _ID_PROMETEO
    assert lic.fuente == "placsp_menores"
    assert lic.analysis_universe == menores.ANALYSIS_UNIVERSE
    assert lic.estado == "RES"
    assert lic.fecha_limite is None
    # La etiqueta normalizada es la columna que mete una fila en el listado, la
    # superficie pública y los KPIs: va vacía. La evidencia queda en keywords.
    assert lic.tecnologia is None
    assert "desarrollo evolutivo" in (lic.raw_keywords or "")
    assert lic.inclusion_reason == "contrato_menor_keyword"
    assert lic.filter_version


def test_un_contrato_menor_conserva_su_adjudicatario():
    _, parseados = _menores_parseados()
    parsed = parseados[0]
    assert parsed is not None

    assert [(a.licitacion_id, a.nif, a.nombre) for a in parsed.adjudicaciones] == [
        (_ID_PROMETEO, "B74197708", "PROMETEO INNOVATIONS S.L.")
    ]


def test_contratos_menores_pasan_la_misma_puerta_tecnologica_que_placsp():
    conector, parseados = _menores_parseados()

    assert parseados[3] is None  # suministro de ortoprótesis
    cpv = parseados[1]
    assert cpv is not None
    assert cpv.licitacion.cpv == _CPV_TI
    assert cpv.licitacion.inclusion_reason == "contrato_menor_cpv_ti"
    assert cpv.licitacion.raw_keywords is None
    # La ortoprótesis y los dos «1/2026» (obras de un parque) no tienen señal.
    assert conector.contadores_de_descarte()["placsp_menores_sin_senal_tecnologica"] == 3


def _con_estado_y_plazo(posicion: int, estado: str | None, plazo: str) -> tuple[Any, str]:
    """La entrada real de *posicion*, con el estado cambiado y un plazo vivo.

    El feed real trae todos los menores cerrados (RES) y sin plazo; el caso que
    el conector debe resistir —un menor sin estado o con uno abierto, y con un
    plazo— se fabrica sobre una entrada real en vez de inventar una entera.
    """
    entry, updated = _entrada_menor(posicion)
    [codigo] = entry.xpath(
        "./cacext:ContractFolderStatus/cbcext:ContractFolderStatusCode", namespaces=_NS
    )
    if estado is None:
        codigo.getparent().remove(codigo)
        # El parser cae al «Estado: …» del resumen cuando falta el código.
        resumen = entry.find(f"{_ATOM_NS}summary")
        resumen.text = resumen.text.split("; Estado:")[0]
    else:
        codigo.text = estado
    [proceso] = entry.xpath("./cacext:ContractFolderStatus/cac:TenderingProcess", namespaces=_NS)
    periodo = etree.SubElement(proceso, etree.QName(_NS["cac"], "TenderSubmissionDeadlinePeriod"))
    etree.SubElement(periodo, etree.QName(_NS["cbc"], "EndDate")).text = plazo
    etree.SubElement(periodo, etree.QName(_NS["cbc"], "EndTime")).text = "12:00:00"
    return entry, updated


@pytest.mark.parametrize("estado", [None, "PUB"])
def test_un_contrato_menor_sin_estado_o_con_plazo_se_guarda_cerrado_y_sin_plazo(estado):
    """Lo que lo mantiene fuera del Radar no puede depender de que el feed lo diga.

    El Radar exige estado abierto **y** plazo vivo (``scoring_candidates``) y el
    filtro «solo abiertas» cuenta ``NULL`` como abierta. Un contrato menor no
    tiene convocatoria: está adjudicado cuando se publica.
    """
    conector = menores.PlacspContratosMenoresConnector(menores.URL_SINDICACION_1143)
    entry, updated = _con_estado_y_plazo(0, estado, "2099-11-15")

    parsed = conector.parse(_raw(entry, updated))

    assert parsed is not None
    assert parsed.licitacion.estado == "RES"
    assert parsed.licitacion.fecha_limite is None
    assert conector.contadores_de_descarte()["placsp_menores_estado_cerrado_por_defecto"] == 1


def test_el_estado_cerrado_del_feed_se_respeta():
    conector = menores.PlacspContratosMenoresConnector(menores.URL_SINDICACION_1143)
    entry, updated = _con_estado_y_plazo(0, "ADJ", "2099-11-15")

    parsed = conector.parse(_raw(entry, updated))

    assert parsed is not None
    assert parsed.licitacion.estado == "ADJ"
    assert conector.contadores_de_descarte()["placsp_menores_estado_cerrado_por_defecto"] == 0


def test_el_universo_de_menores_no_es_ninguno_de_los_tecnologicos():
    from db.sql_fragments import UNIVERSOS_TECNOLOGICOS

    assert menores.ANALYSIS_UNIVERSE not in UNIVERSOS_TECNOLOGICOS


# ── Contratos menores: la identidad ──────────────────────────────────────────


def test_dos_organos_con_el_mismo_expediente_no_comparten_clave(monkeypatch):
    """Medido contra el feed real: 327 de 9.563 ContractFolderID los usan varios órganos.

    Las dos últimas entradas de la fixture son dos órganos reales distintos con
    el expediente «1/2026». Con la clave ``placsp_menores:<expediente>`` el
    segundo upsert pisaba al primero (``ON CONFLICT(id_externo)``). Ninguna de
    las dos pasa la puerta tecnológica, así que se abre para este test: lo que
    se comprueba es la clave, no el filtro.
    """
    from scraper.puerta_tecnologica import MOTIVO_CPV_TI, SenalTecnologica

    monkeypatch.setattr(
        "scraper.puerta_tecnologica.senal_tecnologica",
        lambda *a, **k: SenalTecnologica(motivo=MOTIVO_CPV_TI),
    )
    conector = menores.PlacspContratosMenoresConnector(menores.URL_SINDICACION_1143)
    primera, segunda = (conector.parse(_raw(*_entrada_menor(i))) for i in (4, 5))

    assert primera is not None and segunda is not None
    assert primera.licitacion.id_externo != segunda.licitacion.id_externo
    assert primera.licitacion.id_externo.endswith(":1/2026")
    assert segunda.licitacion.id_externo.endswith(":1/2026")
    # Cada adjudicación cuelga de la licitación de su propio órgano.
    assert {a.licitacion_id for a in primera.adjudicaciones} == {primera.licitacion.id_externo}
    assert {a.licitacion_id for a in segunda.adjudicaciones} == {segunda.licitacion.id_externo}
    assert {a.nif for a in primera.adjudicaciones} != {a.nif for a in segunda.adjudicaciones}


def test_la_clave_de_un_menor_es_estable_entre_pasadas():
    """Reingerir la misma entrada da la misma clave: el upsert sigue siendo idempotente."""
    primera = menores.PlacspContratosMenoresConnector(menores.URL_SINDICACION_1143)
    segunda = menores.PlacspContratosMenoresConnector(menores.URL_SINDICACION_1143)

    a = primera.parse(_raw(*_entrada_menor(0)))
    b = segunda.parse(_raw(*_entrada_menor(0)))

    assert a is not None and b is not None
    assert a.licitacion.id_externo == b.licitacion.id_externo == _ID_PROMETEO


def test_el_organo_de_la_clave_es_el_id_de_la_plataforma():
    entry, _ = _entrada_menor(0)

    assert menores.identificador_organo(entry) == _ORGANO_PROMETEO
    assert menores.id_externo_menor("123", "1/2026") == "placsp_menores:123:1/2026"


def test_sin_id_de_plataforma_el_organo_cae_al_nif_y_luego_al_dir3():
    entry, _ = _entrada_menor(0)
    ids = {
        n.find("cbc:ID", _NS).get("schemeName"): n for n in entry.xpath(_IDS_ORGANO, namespaces=_NS)
    }
    nif = ids["NIF"].find("cbc:ID", _NS).text
    dir3 = ids["DIR3"].find("cbc:ID", _NS).text

    ids["ID_PLATAFORMA"].getparent().remove(ids["ID_PLATAFORMA"])
    assert menores.identificador_organo(entry) == nif
    ids["NIF"].getparent().remove(ids["NIF"])
    assert menores.identificador_organo(entry) == dir3
    ids["DIR3"].getparent().remove(ids["DIR3"])
    assert menores.identificador_organo(entry) is None


def test_una_entrada_sin_identificador_de_organo_se_descarta_y_se_cuenta():
    conector = menores.PlacspContratosMenoresConnector(menores.URL_SINDICACION_1143)
    entry, updated = _entrada_menor(0)
    for nodo in entry.xpath(_IDS_ORGANO, namespaces=_NS):
        nodo.getparent().remove(nodo)

    assert conector.parse(_raw(entry, updated)) is None
    assert conector.contadores_de_descarte()["placsp_menores_sin_identificador_de_organo"] == 1


def test_el_expediente_natural_de_un_menor_incluye_su_organo():
    """Así el dedupe no casa un menor con la licitación de otro órgano de igual número."""
    from services.dedupe import natural_expediente

    assert natural_expediente(_ID_PROMETEO) == f"{_ORGANO_PROMETEO}:2026/SP03032007/00000540E"


def test_un_adjudicatario_con_nif_enmascarado_no_se_guarda():
    """PLACSP enmascara el NIF de las personas físicas (``***3418**``) y, a veces, el de una SL.

    Una clave así no identifica a nadie: el maestro de empresas fundiría a
    adjudicatarios sin relación. La licitación entra; la adjudicación, no.
    """
    conector, parseados = _menores_parseados()
    enmascarada = parseados[2]
    assert enmascarada is not None

    assert enmascarada.licitacion.id_externo.endswith(":300/2026/03143")
    assert enmascarada.adjudicaciones == []
    assert conector.contadores_de_descarte()["placsp_menores_nif_enmascarado"] == 1


# ── Agregadas: el modelado ───────────────────────────────────────────────────

# Entradas de agregadas_1044.atom, por posición: 0 equipos informáticos de los
# Mercados de Abastecimientos de Barcelona (adjudicada, pliegos en
# contractaciopublica.cat), 1 desarrollo del Ajuntament de Blanes (abierta,
# pliegos en contractaciopublica.cat), 2 consultoría ENS de Bilbao (pliegos en
# contratacion.euskadi.eus), 3 mantenimiento de aplicaciones (3 lotes) y 4
# renovación de parques infantiles (sin señal).
_URL_PLIEGOS_BLANES = (
    "https://contractaciopublica.cat/portal-api/descarrega-document/"
    "302714374/40DCD47D23683DB60DC13F15ABFA3B76",
    "https://contractaciopublica.cat/portal-api/descarrega-document/"
    "302716409/A83F34003DF26B0BF9387936F0C09BE3",
)


def _agregadas_parseadas() -> tuple[agregadas.PlacspAgregadasConnector, list[Any]]:
    conector = agregadas.PlacspAgregadasConnector(agregadas.URL_SINDICACION_1044)
    return conector, [conector.parse(_raw(e, u)) for e, u in _entries("agregadas_1044.atom")]


def test_una_licitacion_agregada_entra_como_oportunidad_con_su_namespace():
    _, parseadas = _agregadas_parseadas()
    parsed = parseadas[1]
    assert parsed is not None
    lic = parsed.licitacion

    assert lic.id_externo == "placsp_agregadas:2026/15089Q"
    assert lic.fuente == "placsp_agregadas"
    assert lic.analysis_universe == "technology_observed"
    assert lic.estado == "PUB"
    assert lic.fecha_limite is not None and lic.fecha_limite.startswith("2026-11-09")
    assert lic.tecnologia == "DESARROLLO"


def test_de_una_agregada_solo_se_guardan_los_pliegos_de_hosts_que_acepta_el_descargador():
    """Los de otro host no pasarían la allowlist del descargador.

    Guardarlos dejaría filas de ``documentos`` condenadas a fallar en cada
    pasada del job de pliegos. En el feed real **ninguna** referencia apunta a
    PLACSP: son de contractaciopublica.cat (en la allowlist por PSCP), de
    contratacion.euskadi.eus y de contratos-publicos.comunidad.madrid (fuera).
    """
    conector, parseadas = _agregadas_parseadas()
    blanes, bilbao = parseadas[1], parseadas[2]
    assert blanes is not None and bilbao is not None

    assert tuple(d.uri for d in blanes.documentos) == _URL_PLIEGOS_BLANES
    assert bilbao.documentos == []
    assert conector.contadores_de_descarte()["placsp_agregadas_documentos_de_otro_host"] == 2


def test_las_agregadas_pasan_el_filtro_de_tecnologia_de_placsp():
    conector, parseadas = _agregadas_parseadas()

    assert parseadas[4] is None  # parques infantiles
    assert all(p is not None for p in parseadas[:4])
    assert parseadas[0].licitacion.id_externo == "placsp_agregadas:AM2024.01ACM_BAM1L2"
    assert conector.contadores_de_descarte()["placsp_agregadas_fuera_de_universo"] == 1


def test_los_lotes_de_una_agregada_cuelgan_de_su_clave_con_namespace():
    _, parseadas = _agregadas_parseadas()
    parsed = parseadas[3]
    assert parsed is not None

    assert len(parsed.lotes) == 3
    assert {lote.licitacion_id for lote in parsed.lotes} == {parsed.licitacion.id_externo}


def test_el_expediente_natural_de_una_agregada_es_el_de_placsp():
    """Es lo que permite al dedupe casarla con la misma fila de otra fuente."""
    from services.dedupe import natural_expediente

    assert natural_expediente("placsp_agregadas:EXP-2026-77") == "EXP-2026-77"


# ── Apagadas por defecto ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("modulo", "variable"),
    [(menores, "PLACSP_MENORES_ATOM_URL"), (agregadas, "PLACSP_AGREGADAS_ATOM_URL")],
)
def test_sin_su_variable_la_fuente_se_declara_apagada_y_no_descarga(
    modulo, variable, monkeypatch, feed
):
    from config import settings

    assert getattr(settings.__class__.model_fields[variable], "default", None) == ""
    monkeypatch.setattr(settings, variable, "")
    apagadas: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "scraper.connectors.base.record_source_disabled",
        lambda source_id, *, motivo: apagadas.append((source_id, motivo)),
    )

    assert modulo.ejecutar() is None

    assert [s for s, _ in apagadas] == [modulo.SOURCE_ID]
    assert variable in apagadas[0][1]
    assert feed["llamadas"] == []


@pytest.mark.parametrize("modulo", [menores, agregadas])
def test_estan_registradas_como_opcionales(modulo):
    fuente = REGISTERED_SOURCES_BY_ID[modulo.SOURCE_ID]

    assert fuente.estado == "opcional"
    assert fuente.modulo == modulo.__name__
    assert "apagad" in fuente.alcance.lower()


def test_los_contratos_menores_siguen_declarados_fuera_de_alcance():
    """D16 no se revoca escribiendo el conector: lo revisa el dueño al activarlo."""
    menores_excluidos = [a for a in FUERA_DE_ALCANCE if "menores" in a.ambito.lower()]
    assert len(menores_excluidos) == 1
    assert "placsp_menores" in menores_excluidos[0].motivo


@pytest.mark.parametrize(
    ("url", "sindicacion"),
    [
        (menores.URL_SINDICACION_1143, "sindicacion_1143/contratosMenoresPerfilesContratantes"),
        (agregadas.URL_SINDICACION_1044, "sindicacion_1044/PlataformasAgregadasSinMenores"),
    ],
)
def test_la_url_documentada_es_la_de_la_sindicacion(url, sindicacion):
    from scraper.atom_live import _is_allowed_url

    assert sindicacion in url
    assert url.startswith("https://contrataciondelsectorpublico.gob.es/sindicacion/")
    assert _is_allowed_url(url)


def test_los_enlaces_next_de_los_feeds_reales_pasan_la_guarda_de_hosts():
    """El feed pagina con ``rel="next"`` hacia ``contrataciondelestado.es`` (host histórico)."""
    from scraper.atom_live import _parse_feed_links

    for nombre in ("contratos_menores_1143.atom", "agregadas_1044.atom"):
        raiz = etree.fromstring((_FIXTURES / nombre).read_bytes())
        siguiente = _parse_feed_links(raiz)
        assert siguiente is not None
        assert siguiente.startswith("https://contrataciondelestado.es/sindicacion/")


# ── Fetch y cursor ───────────────────────────────────────────────────────────


def test_el_fetch_lee_la_url_configurada_desde_el_cursor(feed):
    feed["fichero"] = "contratos_menores_1143.atom"
    conector = menores.PlacspContratosMenoresConnector(menores.URL_SINDICACION_1143)

    vistos = list(conector.fetch({"last_seen_updated": "2026-10-10T00:00:00+02:00"}))

    assert len(vistos) == 6
    assert feed["llamadas"] == [
        {
            "last_seen_updated": "2026-10-10T00:00:00+02:00",
            "start_url": menores.URL_SINDICACION_1143,
        }
    ]
    assert conector.new_cursor() == {
        "last_seen_updated": "2026-10-24T02:06:27.847+02:00",
        "etag": '"e1"',
        "last_modified": None,
    }


@pytest.mark.parametrize(
    "url",
    ["https://evil.example/sindicacion.atom", "ftp://contrataciondelsectorpublico.gob.es/x.atom"],
)
def test_una_url_fuera_de_placsp_se_rechaza(url):
    with pytest.raises(ValueError, match="PLACSP"):
        agregadas.PlacspAgregadasConnector(url)


def test_check_valida_la_primera_pagina_sin_escribir(monkeypatch, tmp_path):
    from unittest.mock import MagicMock

    from scraper.connectors import sindicacion_placsp

    registro = MagicMock()
    monkeypatch.setattr(sindicacion_placsp, "log", registro)
    contenido = (_FIXTURES / "agregadas_1044.atom").read_bytes()
    pedidas: list[str] = []

    class _Pagina:
        content = contenido

    def fetch_atom_page(url: str, **kw: Any) -> _Pagina:
        pedidas.append(url)
        return _Pagina()

    monkeypatch.setattr("scraper.atom_live.fetch_atom_page", fetch_atom_page)
    monkeypatch.setattr(
        "scraper.connectors.base.run_connector",
        lambda *a, **k: pytest.fail("--check no puede ingerir"),
    )
    volcado = tmp_path / "muestra.atom"

    codigo = agregadas.main(["--check", "--dump", str(volcado)])

    assert codigo == 0
    assert pedidas == [agregadas.URL_SINDICACION_1044]
    # El informe del --check va al log estructurado (sin print() en scraper/).
    informe = next(
        c.kwargs for c in registro.info.call_args_list if c.args == ("sindicacion_check",)
    )
    assert informe["entradas"] == 5
    assert informe["admitidas"] == 4
    assert volcado.read_bytes() == contenido


# ---------------------------------------------------------------------------
# Recorrido real contra Postgres
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_db):
    db_mod, _ = tmp_db
    return db_mod


def test_integration_los_menores_no_aparecen_como_licitaciones_y_si_como_adjudicaciones(db, feed):
    from datetime import date

    from db.repositories.aggregates import AggregateRepository
    from db.repositories.licitaciones import LicitacionRepository
    from db.repositories.publico import PublicoRepository
    from scraper.connectors.base import run_connector

    feed["fichero"] = "contratos_menores_1143.atom"
    resultado = run_connector(menores.PlacspContratosMenoresConnector(menores.URL_SINDICACION_1143))

    assert (resultado.parsed, resultado.descartadas, resultado.errores) == (3, 3, 0)
    with db.connect_read() as c:
        filas = c.execute(
            "SELECT id_externo, estado, fecha_limite, tecnologia FROM licitaciones "
            "WHERE fuente = 'placsp_menores' ORDER BY id_externo"
        ).fetchall()
        adjudicaciones = c.execute(
            "SELECT a.licitacion_id, a.nif, a.empresa_id FROM adjudicaciones a "
            "JOIN licitaciones l ON l.id_externo = a.licitacion_id "
            "WHERE l.fuente = 'placsp_menores' ORDER BY a.licitacion_id"
        ).fetchall()
    assert [f[0] for f in filas] == [
        "placsp_menores:11232140166974:2026M0000149",
        _ID_PROMETEO,
        "placsp_menores:31606280204388:300/2026/03143",
    ]
    assert all(f[1] in ("RES", "ADJ") and f[2] is None and f[3] is None for f in filas)
    # Las adjudicaciones entran y la resolución de empresas las enlaza; la de NIF
    # enmascarado (la tercera) no se guarda.
    assert [(a[0], a[1]) for a in adjudicaciones] == [
        ("placsp_menores:11232140166974:2026M0000149", "B84184217"),
        (_ID_PROMETEO, "B74197708"),
    ]
    assert all(a[2] is not None for a in adjudicaciones)

    ids = {f[0] for f in filas}
    radar = AggregateRepository().scoring_candidates(hoy_iso=date.today().isoformat())
    assert not ids & {str(r["id_externo"]) for r in radar}
    listado, _ = LicitacionRepository().list_paginated(limit=100)
    assert not ids & {str(r["id_externo"]) for r in listado}
    for id_externo in ids:
        assert PublicoRepository().ficha(id_externo) is None


def test_integration_dos_menores_con_el_mismo_expediente_de_distinto_organo_conviven(
    db, feed, monkeypatch
):
    """La prueba de punta a punta de la identidad: ``ON CONFLICT(id_externo)`` no los funde."""
    from scraper.connectors.base import run_connector
    from scraper.puerta_tecnologica import MOTIVO_CPV_TI, SenalTecnologica

    monkeypatch.setattr(
        "scraper.puerta_tecnologica.senal_tecnologica",
        lambda *a, **k: SenalTecnologica(motivo=MOTIVO_CPV_TI),
    )
    feed["fichero"] = "contratos_menores_1143.atom"
    run_connector(menores.PlacspContratosMenoresConnector(menores.URL_SINDICACION_1143))
    run_connector(menores.PlacspContratosMenoresConnector(menores.URL_SINDICACION_1143))

    with db.connect_read() as c:
        filas = c.execute(
            "SELECT id_externo FROM licitaciones "
            "WHERE fuente = 'placsp_menores' AND id_externo LIKE %s",
            ("%:1/2026",),
        ).fetchall()
        total = c.execute(
            "SELECT count(*) FROM licitaciones WHERE fuente = 'placsp_menores'"
        ).fetchone()
    # Dos órganos, dos filas; y la segunda pasada no duplica nada.
    assert len(filas) == 2
    assert total[0] == 6


def test_integration_una_agregada_que_ya_entra_por_pscp_queda_marcada_como_duplicada(db, feed):
    from db.repositories.aggregates import AggregateRepository
    from db.upsert import Licitacion
    from scraper.connectors.base import run_connector

    # La de Blanes es la abierta con pareja; la del mantenimiento de aplicaciones
    # (3 lotes), abierta también, no la tiene.
    _, parseadas = _agregadas_parseadas()
    blanes = parseadas[1].licitacion
    db.upsert_licitaciones_with_history(
        [
            Licitacion(
                id_externo="pscp:2026/15089Q",
                titulo=blanes.titulo,
                organo_contratacion=blanes.organo_contratacion,
                cpv=blanes.cpv,
                estado="PUB",
                fuente="pscp",
                tecnologia="DESARROLLO",
                # La canónica entre dos fuentes no PLACSP es la publicada antes.
                fecha_publicacion="2020-01-01",
            )
        ],
        source="pscp",
    )
    feed["fichero"] = "agregadas_1044.atom"

    resultado = run_connector(agregadas.PlacspAgregadasConnector(agregadas.URL_SINDICACION_1044))

    assert (resultado.parsed, resultado.descartadas) == (4, 1)
    with db.connect_read() as c:
        marca = c.execute(
            "SELECT canonical_id, status FROM licitaciones_duplicados WHERE licitacion_id = %s",
            ("placsp_agregadas:2026/15089Q",),
        ).fetchone()
        documentos = c.execute(
            "SELECT uri FROM documentos WHERE licitacion_id = %s ORDER BY uri",
            ("placsp_agregadas:2026/15089Q",),
        ).fetchall()
    assert marca is not None
    assert tuple(marca) == ("pscp:2026/15089Q", "confirmed")
    assert [d[0] for d in documentos] == sorted(_URL_PLIEGOS_BLANES)
    # La que no tiene pareja es una oportunidad del Radar; la duplicada, no. El
    # plazo de las dos es de noviembre de 2026: se mira el día de la muestra.
    radar = {
        str(r["id_externo"]) for r in AggregateRepository().scoring_candidates(hoy_iso="2026-10-24")
    }
    assert "placsp_agregadas:09-7-9.02-0016/2026" in radar
    assert "placsp_agregadas:2026/15089Q" not in radar
