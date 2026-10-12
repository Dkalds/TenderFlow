"""Conectores de las sindicaciones 1143 (contratos menores) y 1044 (agregadas) de PLACSP.

Los dos están **apagados por defecto** (decisión del dueño, revisión de D16):
sin su variable de URL declaran ``disabled`` y no descargan nada. Lo que fija
este fichero:

- Contratos menores: entran filtrados por la misma puerta tecnológica que
  PLACSP, pero **nunca como licitación abierta** —cerrados, sin plazo, fuera
  del universo que alimenta Radar, listado, superficie pública, KPIs y ML— y
  sí con sus adjudicaciones, que es para lo que sirven.
- Agregadas: entran como oportunidades del universo tecnológico, con su
  namespace, y el dedupe las marca cuando el contrato ya entra por otra fuente.

Las fixtures son sintéticas (ver ``tests/fixtures/placsp_sindicaciones/README.md``).
Los ``test_integration_*`` corren contra Postgres.
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


def _menores_parseados() -> tuple[menores.PlacspContratosMenoresConnector, list[Any]]:
    conector = menores.PlacspContratosMenoresConnector(menores.URL_SINDICACION_1143)
    return conector, [
        conector.parse(_raw(e, u)) for e, u in _entries("contratos_menores_1143.atom")
    ]


def test_un_contrato_menor_entra_cerrado_sin_plazo_y_fuera_del_universo_de_licitaciones():
    _, parseados = _menores_parseados()
    parsed = parseados[0]
    assert parsed is not None
    lic = parsed.licitacion

    assert lic.id_externo == "placsp_menores:CM-2026-0412"
    assert lic.fuente == "placsp_menores"
    assert lic.analysis_universe == menores.ANALYSIS_UNIVERSE
    assert lic.estado == "RES"
    assert lic.fecha_limite is None
    # La etiqueta normalizada es la columna que mete una fila en el listado, la
    # superficie pública y los KPIs: va vacía. La evidencia queda en keywords.
    assert lic.tecnologia is None
    assert "microsoft 365" in (lic.raw_keywords or "")
    assert lic.inclusion_reason == "contrato_menor_keyword"
    assert lic.filter_version


def test_un_contrato_menor_conserva_su_adjudicatario():
    _, parseados = _menores_parseados()
    parsed = parseados[0]
    assert parsed is not None

    assert [(a.licitacion_id, a.nif, a.nombre) for a in parsed.adjudicaciones] == [
        ("placsp_menores:CM-2026-0412", "B12345674", "Soluciones Informáticas Ejemplo SL")
    ]


def test_contratos_menores_pasan_la_misma_puerta_tecnologica_que_placsp():
    conector, parseados = _menores_parseados()

    assert parseados[1] is None  # material de limpieza
    cpv = parseados[2]
    assert cpv is not None
    assert cpv.licitacion.inclusion_reason == "contrato_menor_cpv_ti"
    assert cpv.licitacion.raw_keywords is None
    assert conector.contadores_de_descarte()["placsp_menores_sin_senal_tecnologica"] == 1


def test_un_contrato_menor_sin_estado_o_con_plazo_se_guarda_cerrado_y_sin_plazo():
    """Lo que lo mantiene fuera del Radar no puede depender de que el feed lo diga.

    El Radar exige estado abierto **y** plazo vivo (``scoring_candidates``) y el
    filtro «solo abiertas» cuenta ``NULL`` como abierta. Un contrato menor no
    tiene convocatoria: está adjudicado cuando se publica.
    """
    conector, parseados = _menores_parseados()
    defensa = parseados[3]
    assert defensa is not None

    assert defensa.licitacion.estado == "RES"
    assert defensa.licitacion.fecha_limite is None
    assert conector.contadores_de_descarte()["placsp_menores_estado_cerrado_por_defecto"] == 1


def test_el_estado_cerrado_del_feed_se_respeta():
    _, parseados = _menores_parseados()
    adjudicado = parseados[2]
    assert adjudicado is not None
    assert adjudicado.licitacion.estado == "ADJ"


def test_el_universo_de_menores_no_es_ninguno_de_los_tecnologicos():
    from db.sql_fragments import UNIVERSOS_TECNOLOGICOS

    assert menores.ANALYSIS_UNIVERSE not in UNIVERSOS_TECNOLOGICOS


# ── Agregadas: el modelado ───────────────────────────────────────────────────


def _agregadas_parseadas() -> tuple[agregadas.PlacspAgregadasConnector, list[Any]]:
    conector = agregadas.PlacspAgregadasConnector(agregadas.URL_SINDICACION_1044)
    return conector, [conector.parse(_raw(e, u)) for e, u in _entries("agregadas_1044.atom")]


def test_una_licitacion_agregada_entra_como_oportunidad_con_su_namespace():
    _, parseadas = _agregadas_parseadas()
    parsed = parseadas[0]
    assert parsed is not None
    lic = parsed.licitacion

    assert lic.id_externo == "placsp_agregadas:2026/000123"
    assert lic.fuente == "placsp_agregadas"
    assert lic.analysis_universe == "technology_observed"
    assert lic.estado == "PUB"
    assert lic.fecha_limite is not None and lic.fecha_limite.startswith("2099-11-15")
    assert "SAP" in (lic.tecnologia or "")


def test_de_una_agregada_solo_se_guardan_los_pliegos_alojados_en_placsp():
    """Los de otro host no pasarían la allowlist del descargador.

    Guardarlos dejaría filas de ``documentos`` condenadas a fallar en cada
    pasada del job de pliegos.
    """
    conector, parseadas = _agregadas_parseadas()
    parsed = parseadas[0]
    assert parsed is not None

    assert [d.uri for d in parsed.documentos] == [
        "https://contrataciondelestado.es/docs/AGR-EJ-0123-pcap.pdf"
    ]
    assert conector.contadores_de_descarte()["placsp_agregadas_documentos_de_otro_host"] == 1


def test_las_agregadas_pasan_el_filtro_de_tecnologia_de_placsp():
    conector, parseadas = _agregadas_parseadas()

    assert parseadas[1] is None
    tercera = parseadas[2]
    assert tercera is not None
    assert tercera.licitacion.id_externo == "placsp_agregadas:EXP-2026-77"
    assert conector.contadores_de_descarte()["placsp_agregadas_fuera_de_universo"] == 1


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


# ── Fetch y cursor ───────────────────────────────────────────────────────────


def test_el_fetch_lee_la_url_configurada_desde_el_cursor(feed):
    feed["fichero"] = "contratos_menores_1143.atom"
    conector = menores.PlacspContratosMenoresConnector(menores.URL_SINDICACION_1143)

    vistos = list(conector.fetch({"last_seen_updated": "2026-10-10T00:00:00+02:00"}))

    assert len(vistos) == 4
    assert feed["llamadas"] == [
        {
            "last_seen_updated": "2026-10-10T00:00:00+02:00",
            "start_url": menores.URL_SINDICACION_1143,
        }
    ]
    assert conector.new_cursor() == {
        "last_seen_updated": "2026-10-11T18:05:12+02:00",
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


def test_check_valida_la_primera_pagina_sin_escribir(monkeypatch, capsys, tmp_path):
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

    salida = capsys.readouterr().out
    assert codigo == 0
    assert pedidas == [agregadas.URL_SINDICACION_1044]
    assert "3 entradas" in salida
    assert "2 admitidas" in salida
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

    assert (resultado.parsed, resultado.descartadas, resultado.errores) == (3, 1, 0)
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
        "placsp_menores:CM-2026-0412",
        "placsp_menores:CM-2026-0414",
        "placsp_menores:CM-2026-0415",
    ]
    assert all(f[1] in ("RES", "ADJ") and f[2] is None and f[3] is None for f in filas)
    # Las adjudicaciones entran y la resolución de empresas las enlaza.
    assert [(a[0], a[1]) for a in adjudicaciones] == [
        ("placsp_menores:CM-2026-0412", "B12345674"),
        ("placsp_menores:CM-2026-0414", "B00000000"),
    ]
    assert all(a[2] is not None for a in adjudicaciones)

    ids = {f[0] for f in filas}
    radar = AggregateRepository().scoring_candidates(hoy_iso=date.today().isoformat())
    assert not ids & {str(r["id_externo"]) for r in radar}
    listado, _ = LicitacionRepository().list_paginated(limit=100)
    assert not ids & {str(r["id_externo"]) for r in listado}
    for id_externo in ids:
        assert PublicoRepository().ficha(id_externo) is None


def test_integration_una_agregada_que_ya_entra_por_pscp_queda_marcada_como_duplicada(db, feed):
    from datetime import date

    from db.repositories.aggregates import AggregateRepository
    from db.upsert import Licitacion
    from scraper.connectors.base import run_connector

    db.upsert_licitaciones_with_history(
        [
            Licitacion(
                id_externo="pscp:EXP-2026-77",
                titulo="Ampliació de llicències Salesforce Service Cloud",
                organo_contratacion="Consorci d'Exemple",
                cpv="48000000",
                estado="PUB",
                fuente="pscp",
                tecnologia="SALESFORCE",
                fecha_publicacion="2026-10-01",
            )
        ],
        source="pscp",
    )
    feed["fichero"] = "agregadas_1044.atom"

    resultado = run_connector(agregadas.PlacspAgregadasConnector(agregadas.URL_SINDICACION_1044))

    assert (resultado.parsed, resultado.descartadas) == (2, 1)
    with db.connect_read() as c:
        marca = c.execute(
            "SELECT canonical_id, status FROM licitaciones_duplicados WHERE licitacion_id = %s",
            ("placsp_agregadas:EXP-2026-77",),
        ).fetchone()
        documentos = c.execute(
            "SELECT uri FROM documentos WHERE licitacion_id = %s",
            ("placsp_agregadas:2026/000123",),
        ).fetchall()
    assert marca is not None
    assert tuple(marca) == ("pscp:EXP-2026-77", "confirmed")
    assert [d[0] for d in documentos] == [
        "https://contrataciondelestado.es/docs/AGR-EJ-0123-pcap.pdf"
    ]
    # La que no tiene pareja es una oportunidad del Radar; la duplicada, no.
    radar = {
        str(r["id_externo"])
        for r in AggregateRepository().scoring_candidates(hoy_iso=date.today().isoformat())
    }
    assert "placsp_agregadas:2026/000123" in radar
    assert "placsp_agregadas:EXP-2026-77" not in radar
