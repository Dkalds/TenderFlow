"""Documentos de TED y PSCP, que su feed no trae (``scraper.documentos_plataforma``).

Tres caminos: el PDF del anuncio TED, los pliegos de PLACSP rescatados de las
entries del ATOM que el filtro de tecnología descarta, y la ficha JSON de la
PSCP. El JSON de ``tests/fixtures/pscp/detall_publicacio_expedient.json`` es un
recorte real (expediente 2026/6150/1428 de Esplugues, 2026-10-02), con el
anuncio TED 675385-2026 que cita.

Los tests unitarios doblan red y BD. Los ``test_integration_*`` del final
corren contra Postgres.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any

import pybreaker
import pytest
from lxml import etree

import scraper.documentos_plataforma as dp
from db.upsert import DocumentoReferencia
from scraper.documentos_plataforma import (
    RescatePliegosPlacsp,
    numero_publicacion_ted,
    numeros_ted_citados,
    parse_detalle_pscp,
    referencia_anuncio_ted,
    url_api_pscp,
)
from services.dedupe import ReferenciaCruzada, RepublicacionesTed

_FIXTURE_PSCP = Path(__file__).parent / "fixtures" / "pscp" / "detall_publicacio_expedient.json"
_FICHA_PSCP = (
    "https://contractaciopublica.cat/ca/detall-publicacio/"
    "fcd0edf9-2bd9-4f2e-9924-24b8627a96de/300885821"
)
_DEEPLINK = "https://contrataciondelestado.es/wps/poc?uri=deeplink:detalle_licitacion&idEvl="


def _detalle_pscp() -> Any:
    return json.loads(_FIXTURE_PSCP.read_text(encoding="utf-8"))


# ── Anuncio TED ──────────────────────────────────────────────────────────────


def test_anuncio_ted_es_el_pdf_del_aviso_con_identidad_estable():
    ref = referencia_anuncio_ted("ted:678766-2026")

    assert ref == DocumentoReferencia(
        tipo="additional",
        uri="https://ted.europa.eu/es/notice/678766-2026/pdf",
        filename="Anuncio TED 678766-2026.pdf",
        source_hash="ted-678766-2026",
    )


@pytest.mark.parametrize(
    "id_externo", ["2026/ABC", "pscp:2026/1", "ted:", "ted:678766", "ted:../../x-2026"]
)
def test_sin_numero_de_publicacion_valido_no_hay_anuncio(id_externo):
    assert numero_publicacion_ted(id_externo) is None
    assert referencia_anuncio_ted(id_externo) is None


def test_el_source_hash_del_anuncio_es_un_token_valido_para_el_almacen():
    """La clave del binario es ``documentos/{source_hash}`` si el hash es un token seguro."""
    from shared.object_store import document_blob_key

    ref = referencia_anuncio_ted("ted:678766-2026")
    assert ref is not None
    assert document_blob_key(ref.source_hash, fallback="sha") == "documentos/ted-678766-2026"


def test_numeros_ted_citados_en_cualquier_forma_de_enlace_y_sin_repetir():
    nodo = {
        "publicacionsOficials": [
            {"url": "https://ted.europa.eu/en/notice/-/detail/675385-2026"},
            {"url": "https://ted.europa.eu/es/notice/675385-2026/pdf"},
        ],
        "lots": [{"altres": "https://ted.europa.eu/es/notice/-/detail/12-2026"}],
        "boe": "https://www.boe.es/notice/1-2026",
    }

    assert numeros_ted_citados(nodo) == ["675385-2026", "12-2026"]


# ── PSCP ─────────────────────────────────────────────────────────────────────


def test_url_api_de_la_ficha_de_una_publicacion():
    assert url_api_pscp(_FICHA_PSCP) == (
        "https://contractaciopublica.cat/portal-api/detall-publicacio-expedient/"
        "fcd0edf9-2bd9-4f2e-9924-24b8627a96de/300885821"
    )


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        # El BT-15 de los avisos TED catalanes: el perfil del comprador, no el expediente.
        "https://contractaciopublica.cat/ca/perfils-contractant/detall/5281352",
        "https://contractaciopublica.gencat.cat/perfil/TB",
        "https://evil.example/ca/detall-publicacio/fcd0edf9-2bd9-4f2e-9924-24b8627a96de/1",
    ],
)
def test_sin_ficha_de_publicacion_no_hay_url_de_api(url):
    assert url_api_pscp(url) is None


def test_detalle_pscp_mapea_los_apartados_a_tipos_y_usa_el_hash_como_identidad():
    detalle = parse_detalle_pscp(_detalle_pscp())

    por_nombre = {d.filename: d for d in detalle.documentos}
    assert por_nombre["PCAP.pdf"].tipo == "legal"
    assert por_nombre["PPT.pdf"].tipo == "technical"
    assert por_nombre["Informe de necessitat.pdf"].tipo == "additional"
    assert por_nombre["PPT.pdf"].uri == (
        "https://contractaciopublica.cat/portal-api/descarrega-document/"
        "302602166/BED412D30394A796A1E7F7C62352C981"
    )
    # Hash de contenido del PPT que publica el portal, no un secreto.
    huella = "BED412D30394A796A1E7F7C62352C981"  # pragma: allowlist secret
    assert por_nombre["PPT.pdf"].source_hash == huella
    assert len(detalle.documentos) == 5
    assert detalle.anuncios_ted == ["675385-2026"]


def test_detalle_pscp_descarta_documentos_con_id_o_hash_que_compondrian_otra_ruta():
    datos = {
        "dades": {
            "publicacio": {
                "dadesPublicacio": {
                    "altresDocuments": {
                        "docs": [
                            {"id": "1/../../x", "hash": "ABCDEF0123456789", "titol": "a"},
                            {"id": 7, "hash": "AB/CD", "titol": "b"},
                            {"id": 8, "hash": "ABCDEF0123456789", "titol": "  "},
                        ]
                    }
                }
            }
        }
    }

    detalle = parse_detalle_pscp(datos)

    assert [(d.uri.rsplit("/", 2)[-2], d.filename) for d in detalle.documentos] == [("8", None)]


def test_detalle_pscp_sin_publicacion_no_falla():
    assert parse_detalle_pscp({}) == dp.DetallePscp(documentos=[], anuncios_ted=[])
    assert parse_detalle_pscp([]) == dp.DetallePscp(documentos=[], anuncios_ted=[])


def test_documentos_de_pscp_pide_el_json_de_la_ficha():
    pedidas: list[str] = []

    def obtener(url: str) -> bytes:
        pedidas.append(url)
        return _FIXTURE_PSCP.read_bytes()

    detalle = dp.documentos_de_pscp(_FICHA_PSCP, obtener=obtener)

    assert pedidas == [url_api_pscp(_FICHA_PSCP)]
    assert detalle is not None and len(detalle.documentos) == 5


def test_documentos_de_pscp_no_pide_nada_si_la_url_no_es_una_ficha():
    def obtener(url: str) -> bytes:
        raise AssertionError("no debería pedir nada")

    assert (
        dp.documentos_de_pscp("https://contractaciopublica.cat/ca/inici", obtener=obtener) is None
    )


class _RepoFalso:
    def __init__(self, filas: list[dict[str, Any]]) -> None:
        self.filas = filas
        self.escritos: dict[str, list[DocumentoReferencia]] = {}

    def pscp_vigentes_para_documentos(self, limit: int = 200) -> list[dict[str, Any]]:
        return self.filas[:limit]

    def ted_vigentes_sin_documentos(self, limit: int = 300) -> list[str]:
        return [f["id_externo"] for f in self.filas][:limit]

    def upsert_meta(self, licitacion_id: str, refs: list[DocumentoReferencia]) -> int:
        self.escritos[licitacion_id] = refs
        return len(refs)


@pytest.fixture()
def repo_falso(monkeypatch):
    def instalar(filas: list[dict[str, Any]]) -> _RepoFalso:
        repo = _RepoFalso(filas)
        monkeypatch.setattr("db.repositories.documentos.DocumentosRepository", lambda: repo)
        return repo

    return instalar


def test_completar_pscp_escribe_pliegos_y_empareja_el_anuncio_ted(repo_falso, monkeypatch):
    repo = repo_falso([{"id_externo": "pscp:2026/6150/1428", "url": _FICHA_PSCP}])
    marcadas: list[tuple[str, list[str]]] = []

    def marcar(canonica: str, numeros: list[str]) -> RepublicacionesTed:
        marcadas.append((canonica, list(numeros)))
        return RepublicacionesTed(marcadas=[f"ted:{n}" for n in numeros])

    monkeypatch.setattr("services.dedupe.marcar_republicaciones_ted", marcar)

    resumen = dp.completar_documentos_pscp(
        pausa_s=0, obtener=lambda url: _FIXTURE_PSCP.read_bytes()
    )

    assert len(repo.escritos["pscp:2026/6150/1428"]) == 5
    assert marcadas == [("pscp:2026/6150/1428", ["675385-2026"])]
    assert (resumen.candidatas, resumen.con_documentos, resumen.emparejadas) == (1, 1, 1)


def test_si_la_ficha_pscp_no_se_publica_sus_pliegos_van_al_anuncio_ted(repo_falso, monkeypatch):
    """PSCP guarda sin etiqueta lo que entra solo por CPV; TED lo publica igual."""
    repo = repo_falso([{"id_externo": "pscp:2026/6150/1428", "url": _FICHA_PSCP}])
    monkeypatch.setattr(
        "services.dedupe.marcar_republicaciones_ted",
        lambda canonica, numeros: RepublicacionesTed(sin_canonica_visible=["ted:675385-2026"]),
    )

    resumen = dp.completar_documentos_pscp(
        pausa_s=0, obtener=lambda url: _FIXTURE_PSCP.read_bytes()
    )

    assert repo.escritos["ted:675385-2026"] == repo.escritos["pscp:2026/6150/1428"]
    assert len(repo.escritos["ted:675385-2026"]) == 5
    assert (resumen.con_documentos, resumen.emparejadas) == (2, 0)


def test_completar_pscp_corta_tras_cinco_fallos_seguidos(repo_falso, monkeypatch):
    filas = [{"id_externo": f"pscp:{i}", "url": _FICHA_PSCP} for i in range(20)]
    repo_falso(filas)
    monkeypatch.setattr(
        "services.dedupe.marcar_republicaciones_ted", lambda *a: RepublicacionesTed()
    )
    pedidas = 0

    def caida(url: str) -> bytes:
        nonlocal pedidas
        pedidas += 1
        raise ConnectionError("plataforma caída")

    resumen = dp.completar_documentos_pscp(pausa_s=0, obtener=caida)

    assert pedidas == 5
    assert resumen.fallidas == 5
    assert len(resumen.as_dict()["errores"]) == 5


def test_completar_pscp_respeta_el_presupuesto(repo_falso, monkeypatch):
    repo_falso([{"id_externo": f"pscp:{i}", "url": _FICHA_PSCP} for i in range(3)])
    monkeypatch.setattr(
        "services.dedupe.marcar_republicaciones_ted", lambda *a: RepublicacionesTed()
    )

    resumen = dp.completar_documentos_pscp(
        presupuesto_s=-1, pausa_s=0, obtener=lambda url: _FIXTURE_PSCP.read_bytes()
    )

    assert resumen.sin_presupuesto
    assert resumen.candidatas == 0


def test_completar_ted_da_el_anuncio_a_cada_candidata(repo_falso):
    repo = repo_falso([{"id_externo": "ted:1-2026"}, {"id_externo": "ted:2-2026"}])

    resumen = dp.completar_documentos_ted()

    assert [r.uri for r in repo.escritos["ted:1-2026"]] == [
        "https://ted.europa.eu/es/notice/1-2026/pdf"
    ]
    assert set(repo.escritos) == {"ted:1-2026", "ted:2-2026"}
    assert resumen.con_documentos == 2


# ── PLACSP: rescate desde el ATOM ────────────────────────────────────────────

_REF_PCAP = DocumentoReferencia(
    tipo="legal", uri="https://contrataciondelestado.es/pcap.pdf", source_hash="h1"
)


def test_rescate_guarda_los_pliegos_para_el_aviso_ted_que_los_espera():
    rescate = RescatePliegosPlacsp(
        cargar=lambda: [("ted:9-2026", f"{_DEEPLINK}CEGLc1%2fkxg%2fE6P%2fuLemXRw%3d%3d")]
    )

    # El ATOM escribe el escape en mayúsculas y TED a veces en minúsculas.
    n = rescate.considerar(f"{_DEEPLINK}CEGLc1%2Fkxg%2FE6P%2FuLemXRw%3D%3D", [_REF_PCAP])

    assert n == 1
    assert rescate.rescatados == {"ted:9-2026": [_REF_PCAP]}


def test_rescate_se_queda_con_la_version_mas_reciente_de_la_entry():
    """El ATOM va de más nuevo a más viejo; el ZIP mensual, al revés."""
    viejo = DocumentoReferencia(tipo="legal", uri="https://contrataciondelestado.es/v1.pdf")
    nuevo = DocumentoReferencia(tipo="legal", uri="https://contrataciondelestado.es/v2.pdf")
    for orden in (
        [("2026-09-20T10:00:00+02:00", nuevo), ("2026-09-01T10:00:00+02:00", viejo)],
        [("2026-09-01T10:00:00+02:00", viejo), ("2026-09-20T10:00:00+02:00", nuevo)],
    ):
        rescate = RescatePliegosPlacsp(cargar=lambda: [("ted:9-2026", f"{_DEEPLINK}AAA")])
        for actualizado, ref in orden:
            rescate.considerar(f"{_DEEPLINK}AAA", [ref], actualizado)
        assert rescate.rescatados == {"ted:9-2026": [nuevo]}


def test_rescate_ignora_las_entries_que_nadie_espera_y_carga_el_mapa_una_vez():
    cargas = 0

    def cargar() -> list[tuple[str, str | None]]:
        nonlocal cargas
        cargas += 1
        return [("ted:9-2026", f"{_DEEPLINK}AAA")]

    rescate = RescatePliegosPlacsp(cargar=cargar)
    rescate.considerar(f"{_DEEPLINK}BBB", [_REF_PCAP])
    rescate.considerar(f"{_DEEPLINK}CCC", [_REF_PCAP])

    assert rescate.rescatados == {}
    assert cargas == 1


def test_rescate_no_toca_la_bd_sin_pliegos_o_sin_idevl():
    def cargar() -> list[tuple[str, str | None]]:
        raise AssertionError("no debería cargar")

    rescate = RescatePliegosPlacsp(cargar=cargar)

    assert rescate.considerar(f"{_DEEPLINK}AAA", []) == 0
    assert rescate.considerar("https://example.com/sin-idevl", [_REF_PCAP]) == 0


def test_si_la_carga_falla_el_rescate_se_apaga_sin_lanzar():
    def cargar() -> list[tuple[str, str | None]]:
        raise RuntimeError("DATABASE_URL no está configurada")

    rescate = RescatePliegosPlacsp(cargar=cargar)

    assert rescate.considerar(f"{_DEEPLINK}AAA", [_REF_PCAP]) == 0
    assert rescate.considerar(f"{_DEEPLINK}AAA", [_REF_PCAP]) == 0


def test_persistir_escribe_lo_rescatado_y_vacia(repo_falso):
    repo = repo_falso([])
    rescate = RescatePliegosPlacsp(cargar=lambda: [("ted:9-2026", f"{_DEEPLINK}AAA")])
    rescate.considerar(f"{_DEEPLINK}AAA", [_REF_PCAP])

    assert rescate.persistir() == 1
    assert repo.escritos == {"ted:9-2026": [_REF_PCAP]}
    assert rescate.persistir() == 0


_NS = {
    "cbc": "urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2",
    "cacext": "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2",
    "cbcext": "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2",
}


#: El deeplink tal como va dentro de un XML: el ``&`` escapado.
_DEEPLINK_XML = _DEEPLINK.replace("&", "&amp;")


def _entry_descartada_con_pliegos() -> Any:
    """Entry fuera del universo tecnológico (jardinería, CPV 77) con su PCAP."""
    xml = textwrap.dedent(f"""\
        <feed xmlns="http://www.w3.org/2005/Atom">
        <entry xmlns:cbc="{_NS["cbc"]}" xmlns:cac="{_NS["cac"]}"
               xmlns:cacext="{_NS["cacext"]}" xmlns:cbcext="{_NS["cbcext"]}">
          <id>{_DEEPLINK_XML}JARDIN%3D%3D</id>
          <title>Servicio de limpieza de jardines municipales</title>
          <updated>2026-06-14T09:12:33+02:00</updated>
          <link href="{_DEEPLINK_XML}JARDIN%3D%3D" rel="alternate"/>
          <cacext:ContractFolderStatus>
            <cbc:ContractFolderID>2026-JARDIN</cbc:ContractFolderID>
            <cac:ProcurementProject>
              <cbc:Name>Servicio de limpieza de jardines municipales</cbc:Name>
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


def test_la_entry_descartada_por_el_atom_cede_sus_pliegos_al_aviso_ted(monkeypatch):
    from scraper.connectors.placsp import _PlacspParseCore

    monkeypatch.setattr("scraper.pipeline._ml_classify_entry", lambda entry: None)
    core = _PlacspParseCore()
    core.rescate = RescatePliegosPlacsp(cargar=lambda: [("ted:5-2026", f"{_DEEPLINK}JARDIN%3d%3d")])

    parsed = core.parse_entry_elem(_entry_descartada_con_pliegos(), fuente="placsp")

    assert parsed is None
    assert [r.uri for r in core.rescate.rescatados["ted:5-2026"]] == [
        "https://contrataciondelestado.es/pcap-jardin.pdf"
    ]


def test_un_rescate_roto_no_cambia_el_resultado_del_parseo(monkeypatch):
    from scraper.connectors.placsp import _PlacspParseCore

    monkeypatch.setattr("scraper.pipeline._ml_classify_entry", lambda entry: None)
    core = _PlacspParseCore()

    def roto(url: str | None, documentos: list[DocumentoReferencia]) -> int:
        raise RuntimeError("roto")

    monkeypatch.setattr(core.rescate, "considerar", roto)

    assert core.parse_entry_elem(_entry_descartada_con_pliegos(), fuente="placsp") is None


def test_los_conectores_de_placsp_persisten_lo_rescatado(monkeypatch):
    from scraper.connectors.placsp import PlacspAtomConnector, PlacspBulkConnector

    for conector in (PlacspAtomConnector(), PlacspBulkConnector(2026, 9)):
        llamadas: list[str] = []
        monkeypatch.setattr(
            conector._core.rescate,
            "persistir",
            lambda llamadas=llamadas: llamadas.append("x") or 0,
        )
        conector.completar_documentos()
        assert llamadas == ["x"]


# ── Conectores y runner ──────────────────────────────────────────────────────


def test_ted_reempareja_antes_de_dar_anuncios_y_un_fallo_no_salta_el_otro(monkeypatch):
    from scraper.connectors.ted import TedConnector

    orden: list[str] = []

    def reemparejar() -> Any:
        orden.append("reemparejar")
        raise RuntimeError("BD caída")

    def completar() -> dp.ResumenDocumentos:
        orden.append("anuncios")
        return dp.ResumenDocumentos()

    monkeypatch.setattr("services.dedupe.reemparejar_ted_por_id_evl", reemparejar)
    monkeypatch.setattr("scraper.documentos_plataforma.completar_documentos_ted", completar)

    TedConnector().completar_documentos()

    assert orden == ["reemparejar", "anuncios"]


def test_post_ingestion_completa_documentos_tras_el_dedupe_y_es_fail_open(monkeypatch):
    from scraper.connectors import base

    orden: list[str] = []
    monkeypatch.setattr(
        "services.entity_resolution.resolve_all_unlinked", lambda **kw: orden.append("empresas")
    )
    monkeypatch.setattr("services.dedupe.detect_duplicates", lambda **kw: orden.append("dedupe"))
    monkeypatch.setattr(
        "services.dedupe.detect_duplicados_por_referencia",
        lambda **kw: orden.append("referencias"),
    )
    monkeypatch.setattr(
        "services.contract_events.derive_new_events", lambda: orden.append("eventos")
    )
    monkeypatch.setattr(
        "shared.cache_signal.signal_cache_invalidation", lambda: orden.append("cache")
    )

    def completar() -> None:
        orden.append("documentos")
        raise RuntimeError("plataforma caída")

    base._post_ingestion(
        "ted",
        referencias={"ted:1-2026": ReferenciaCruzada(id_evl="CEGLc1/kxg/E6P/uLemXRw==")},
        completar_documentos=completar,
    )

    assert orden == ["empresas", "dedupe", "referencias", "documentos", "eventos", "cache"]


def test_completar_documentos_es_opt_in_por_atributo():
    from scraper.connectors.base import _completar_documentos_de
    from scraper.connectors.pscp import PscpConnector
    from scraper.connectors.ted import TedConnector

    class _Sin:
        source_id = "x"

    assert _completar_documentos_de(_Sin()) is None  # type: ignore[arg-type]
    assert _completar_documentos_de(TedConnector()) is not None
    assert _completar_documentos_de(PscpConnector()) is not None


# ── Red: un circuito por plataforma ──────────────────────────────────────────


@pytest.mark.parametrize(
    ("host", "nombre"),
    [
        ("ted.europa.eu", "ted"),
        ("contractaciopublica.cat", "pscp"),
        ("contrataciondelestado.es", "placsp"),
        ("www.contrataciondelestado.es", "placsp"),
        ("eviltd.europa.eu.example", "placsp"),
        (None, "placsp"),
    ],
)
def test_breaker_por_host(host, nombre):
    from scraper.resilience import breaker_para_host

    assert breaker_para_host(host).name == nombre


def test_la_descarga_pasa_por_el_circuito_de_su_plataforma(monkeypatch):
    import scraper.document_fetcher as df

    usados: list[str | None] = []
    circuito = pybreaker.CircuitBreaker()

    def breaker(host: str | None) -> pybreaker.CircuitBreaker:
        usados.append(host)
        return circuito

    monkeypatch.setattr(df, "breaker_para_host", breaker)
    monkeypatch.setattr(
        df, "_download_bytes_con_reintentos", lambda uri: (b"%PDF", "application/pdf")
    )

    assert df._download_bytes("https://ted.europa.eu/es/notice/1-2026/pdf") == (
        b"%PDF",
        "application/pdf",
    )
    assert usados == ["ted.europa.eu"]


# ---------------------------------------------------------------------------
# Recorrido real contra Postgres
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_db):
    db_mod, _ = tmp_db
    return db_mod


def _dia(desplazamiento: int) -> str:
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC).date() + timedelta(days=desplazamiento)).isoformat()


def _insertar(c: Any, id_externo: str, **campos: Any) -> None:
    fila: dict[str, Any] = {
        "titulo": "Suministro de licencias de software de gestión documental",
        "organo_contratacion": "Ajuntament d'Esplugues de Llobregat",
        "cpv": "48000000",
        "importe": 120000.0,
        "url": None,
        "fecha_publicacion": _dia(-3),
        "fecha_limite": _dia(20),
        "estado": "PUB",
        "fuente": id_externo.split(":", 1)[0] if ":" in id_externo else "placsp",
        "fecha_extraccion": _dia(0),
        "tecnologia": None,
        "analysis_universe": "technology_observed",
    }
    fila.update(campos)
    columnas = ["id_externo", *fila]
    c.execute(
        f"INSERT INTO licitaciones ({', '.join(columnas)}) "  # noqa: S608 — columnas fijas del test
        f"VALUES ({', '.join(['%s'] * len(columnas))})",
        (id_externo, *fila.values()),
    )


def _documento(c: Any, licitacion_id: str) -> None:
    c.execute(
        "INSERT INTO documentos (licitacion_id, tipo, uri) VALUES (%s, 'legal', %s)",
        (licitacion_id, f"https://contrataciondelestado.es/{licitacion_id}.pdf"),
    )


def _marca(c: Any, licitacion_id: str) -> tuple[Any, ...] | None:
    fila = c.execute(
        "SELECT canonical_id, status FROM licitaciones_duplicados WHERE licitacion_id = %s",
        (licitacion_id,),
    ).fetchone()
    return tuple(fila) if fila else None


def test_integration_ted_vigentes_sin_documentos(db) -> None:
    from db.database import connect
    from db.repositories.documentos import DocumentosRepository

    with connect() as c:
        _insertar(c, "ted:1-2026")  # vigente, sin nada: entra
        _insertar(c, "ted:2-2026")
        _documento(c, "ted:2-2026")  # ya tiene documentos
        _insertar(c, "EXP-CANON")
        _insertar(c, "ted:3-2026")
        c.execute(
            "INSERT INTO licitaciones_duplicados (licitacion_id, canonical_id, clave_match, "
            " confianza, status) VALUES ('ted:3-2026', 'EXP-CANON', 'idEvl:x', 1.0, 'confirmed')"
        )
        _insertar(c, "ted:4-2026", fecha_limite=_dia(-1))  # plazo vencido
        _insertar(c, "ted:5-2026", estado="RES")  # adjudicación
        _insertar(c, "ted:6-2026", estado="PRE", fecha_limite=None)  # previo reciente: entra
        _insertar(c, "ted:7-2026", estado="PRE", fecha_limite=None, fecha_publicacion=_dia(-200))

    assert set(DocumentosRepository().ted_vigentes_sin_documentos()) == {"ted:1-2026", "ted:6-2026"}


def test_integration_completar_ted_pone_el_anuncio_una_sola_vez(db) -> None:
    from db.database import connect, connect_read

    with connect() as c:
        _insertar(c, "ted:678766-2026")

    primera = dp.completar_documentos_ted()
    segunda = dp.completar_documentos_ted()

    assert (primera.con_documentos, segunda.candidatas) == (1, 0)
    with connect_read() as c:
        filas = c.execute(
            "SELECT tipo, uri, source_hash, status FROM documentos WHERE licitacion_id = %s",
            ("ted:678766-2026",),
        ).fetchall()
    assert [tuple(f) for f in filas] == [
        (
            "additional",
            "https://ted.europa.eu/es/notice/678766-2026/pdf",
            "ted-678766-2026",
            "pending",
        )
    ]


def test_integration_pscp_vigentes_para_documentos(db) -> None:
    from db.database import connect
    from db.repositories.documentos import DocumentosRepository

    with connect() as c:
        _insertar(c, "pscp:SIN-DOCS", analysis_universe="pscp_observed", tecnologia="SAP")
        _insertar(c, "pscp:RECIENTE", analysis_universe="pscp_observed", tecnologia="SAP")
        _documento(c, "pscp:RECIENTE")
        _insertar(
            c,
            "pscp:YA-LEIDA",
            analysis_universe="pscp_observed",
            tecnologia="SAP",
            fecha_publicacion=_dia(-40),
        )
        _documento(c, "pscp:YA-LEIDA")
        _insertar(c, "pscp:LIMPIEZA", analysis_universe="pscp_observed", tecnologia=None)
        # Solo por CPV 48/72: no se publica, pero su anuncio TED sí.
        _insertar(
            c,
            "pscp:SOLO-CPV",
            analysis_universe="pscp_observed",
            inclusion_reason="cpv_ti_universe",
        )
        _insertar(
            c, "pscp:CERRADA", analysis_universe="pscp_observed", tecnologia="SAP", estado="ADJ"
        )

    filas = DocumentosRepository().pscp_vigentes_para_documentos()

    # Sin documentos primero; la ya leída hace 40 días no se vuelve a pedir.
    assert [f["id_externo"] for f in filas] == ["pscp:SIN-DOCS", "pscp:SOLO-CPV", "pscp:RECIENTE"]


def test_integration_reempareja_los_ted_antiguos_por_id_evl(db) -> None:
    from db.database import connect, connect_read
    from services.dedupe import reemparejar_ted_por_id_evl

    url = f"{_DEEPLINK}CEGLc1%2Fkxg%2FE6P%2FuLemXRw%3D%3D"
    with connect() as c:
        _insertar(c, "2025/EXP-1", url=url, organo_contratacion="Ministerio")
        _insertar(c, "ted:400000-2026", url=url.replace("%2F", "%2f"), fecha_publicacion=_dia(-60))
        _insertar(c, "ted:400001-2026", url="https://ted.europa.eu/es/notice/400001-2026/pdf")

    resultado = reemparejar_ted_por_id_evl()

    assert resultado.confirmados == 1
    with connect_read() as c:
        assert _marca(c, "ted:400000-2026") == ("2025/EXP-1", "confirmed")
        assert _marca(c, "ted:400001-2026") is None
    # Lo ya emparejado sale de la consulta: reejecutar no evalúa nada.
    assert reemparejar_ted_por_id_evl().evaluadas == 0


def test_integration_la_ficha_pscp_empareja_su_anuncio_ted(db) -> None:
    from db.database import connect, connect_read
    from services.dedupe import marcar_republicaciones_ted

    with connect() as c:
        _insertar(c, "pscp:2026/6150/1428", analysis_universe="pscp_observed", tecnologia="SAP")
        _insertar(c, "ted:675385-2026")

    resultado = marcar_republicaciones_ted("pscp:2026/6150/1428", ["675385-2026", "999-2026"])

    assert resultado == RepublicacionesTed(marcadas=["ted:675385-2026"])
    with connect_read() as c:
        assert _marca(c, "ted:675385-2026") == ("pscp:2026/6150/1428", "confirmed")


def test_integration_no_esconde_el_ted_tras_una_ficha_pscp_que_no_se_publica(db) -> None:
    from db.database import connect, connect_read
    from services.dedupe import marcar_republicaciones_ted

    with connect() as c:
        # Fuera del universo tecnológico: la superficie pública no la sirve.
        _insertar(c, "pscp:LIMPIEZA", analysis_universe="pscp_observed", tecnologia=None)
        _insertar(c, "ted:675386-2026")

    resultado = marcar_republicaciones_ted("pscp:LIMPIEZA", ["675386-2026"])

    assert resultado == RepublicacionesTed(sin_canonica_visible=["ted:675386-2026"])
    with connect_read() as c:
        assert _marca(c, "ted:675386-2026") is None


def test_integration_el_rescate_escribe_los_pliegos_en_la_fila_ted(db) -> None:
    from db.database import connect, connect_read

    with connect() as c:
        _insertar(c, "ted:500000-2026", url=f"{_DEEPLINK}JARDIN%3D%3D")

    rescate = RescatePliegosPlacsp()
    assert rescate.considerar(f"{_DEEPLINK}JARDIN%3d%3d", [_REF_PCAP]) == 1
    assert rescate.persistir() == 1
    with connect_read() as c:
        uris = [
            r[0]
            for r in c.execute(
                "SELECT uri FROM documentos WHERE licitacion_id = %s", ("ted:500000-2026",)
            ).fetchall()
        ]
    assert uris == ["https://contrataciondelestado.es/pcap.pdf"]
