"""Documentos de TED y PSCP, que su feed no trae (``scraper.documentos_plataforma``).

Dos caminos: el PDF del anuncio TED y la ficha JSON de la PSCP (el expediente
de PLACSP que enlaza un aviso TED lo ingiere el propio conector:
``tests/test_placsp_esperadas_por_ted.py``). El JSON de ``tests/fixtures/pscp/detall_publicacio_expedient.json`` es un
recorte real (expediente 2026/6150/1428 de Esplugues, 2026-10-02), con el
anuncio TED 675385-2026 que cita. ``fase_formalitzacio.json`` y
``fase_anunci.json`` son otros dos (expediente SER_NSP_2026_0002, resuelto,
2026-11-09): la publicación de su última fase, que es la que guarda
``licitaciones.url``, y la del anuncio que enlaza su ``navegacioFases``.
``fixtures/andalucia/expediente_1036313.json`` es la respuesta real del buscador
del Perfil de Contratante de la Junta para EXPT26-00040 (SANDETEL, 2026-11-09),
recortada a lo que se lee.

Los tests unitarios doblan red y BD. Los ``test_integration_*`` del final
corren contra Postgres.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pybreaker
import pytest

import scraper.documentos_plataforma as dp
from db.upsert import DocumentoReferencia
from scraper.documentos_plataforma import (
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
_FIXTURE_FORMALITZACIO = _FIXTURE_PSCP.with_name("fase_formalitzacio.json")
_FIXTURE_ANUNCI = _FIXTURE_PSCP.with_name("fase_anunci.json")
_FICHA_CERRADA = (
    "https://contractaciopublica.cat/ca/detall-publicacio/"
    "5f414a80-c061-48ab-b865-8cc23e05e3af/300751065"
)
_API_EXPEDIENTE_CERRADO = (
    "https://contractaciopublica.cat/portal-api/detall-publicacio-expedient/"
    "5f414a80-c061-48ab-b865-8cc23e05e3af"
)


def _detalle_pscp() -> Any:
    return json.loads(_FIXTURE_PSCP.read_text(encoding="utf-8"))


def _formalitzacio() -> Any:
    return json.loads(_FIXTURE_FORMALITZACIO.read_text(encoding="utf-8"))


def _portal(por_publicacion: dict[str, Any], pedidas: list[str]) -> Any:
    """Un ``obtener`` que sirve el JSON de cada publicación del expediente cerrado."""

    def obtener(url: str) -> bytes:
        pedidas.append(url)
        return json.dumps(por_publicacion[url.rsplit("/", 1)[-1]]).encode()

    return obtener


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


def test_los_documentos_de_otra_fase_no_entran_como_pliego():
    """El contrato firmado de la formalización, como ``additional``, iría al RAG y a la ficha."""
    assert parse_detalle_pscp(_formalitzacio()).documentos == []


def test_un_expediente_cerrado_lee_los_pliegos_de_su_anuncio():
    pedidas: list[str] = []
    anunci = json.loads(_FIXTURE_ANUNCI.read_text(encoding="utf-8"))
    portal = _portal({"300751065": _formalitzacio(), "300719618": anunci}, pedidas)

    detalle = dp.documentos_de_pscp(_FICHA_CERRADA, obtener=portal)

    assert pedidas == [
        f"{_API_EXPEDIENTE_CERRADO}/300751065",
        f"{_API_EXPEDIENTE_CERRADO}/300719618",
    ]
    assert detalle is not None
    assert [(d.tipo, d.filename) for d in detalle.documentos] == [
        ("legal", "SER_NSP_2026_0002-PCAP_diligenciat.pdf"),
        ("technical", "SER_NSP_2026_0002-PPT-diligenciat.pdf"),
        ("additional", "SER_NSP_2026_0002-Informe previ.pdf"),
        ("additional", "SER_NSP_2026_0002-Decret aprovar Plecs_CA.pdf"),
    ]


def test_solo_vale_el_aviso_ted_que_cita_la_ficha_del_anuncio():
    """El de otra fase podría ser el del acuerdo marco, y se marcaría ``confirmed``."""

    def citando(datos: Any, numero: str) -> Any:
        datos["dades"]["publicacio"]["publicacionsOficials"] = [
            {"tipus": {"text": "DOUE"}, "url": f"https://ted.europa.eu/en/notice/-/detail/{numero}"}
        ]
        return datos

    anunci = json.loads(_FIXTURE_ANUNCI.read_text(encoding="utf-8"))
    portal = _portal(
        {
            "300751065": citando(_formalitzacio(), "111111-2026"),
            "300719618": citando(anunci, "222222-2026"),
        },
        [],
    )

    detalle = dp.documentos_de_pscp(_FICHA_CERRADA, obtener=portal)

    assert detalle is not None and detalle.anuncios_ted == ["222222-2026"]


def test_sin_anuncio_en_la_plataforma_no_hay_nada_mas_que_pedir():
    """Un negociado sin publicidad o un contrato basado en un acuerdo marco no lo tuvo."""
    datos = _formalitzacio()
    datos["navegacioFases"] = [f for f in datos["navegacioFases"] if f["fase"] != 1000040]
    pedidas: list[str] = []

    detalle = dp.documentos_de_pscp(_FICHA_CERRADA, obtener=_portal({"300751065": datos}, pedidas))

    assert pedidas == [f"{_API_EXPEDIENTE_CERRADO}/300751065"]
    assert detalle == dp.DetallePscp(documentos=[], anuncios_ted=[])


@pytest.mark.parametrize("publicacion", ["1/../../x", "300719618?a=1", "", None, 12345678901234])
def test_un_id_de_publicacion_que_compondria_otra_ruta_no_se_pide(publicacion):
    datos = _formalitzacio()
    datos["navegacioFases"] = [{"fase": 1000040, "publicacioId": publicacion}]
    pedidas: list[str] = []

    dp.documentos_de_pscp(_FICHA_CERRADA, obtener=_portal({"300751065": datos}, pedidas))

    assert pedidas == [f"{_API_EXPEDIENTE_CERRADO}/300751065"]


_FIXTURE_ANDALUCIA = Path(__file__).parent / "fixtures" / "andalucia" / "expediente_1036313.json"
_FICHA_ANDALUCIA = (
    "https://www.juntadeandalucia.es/haciendayadministracionpublica/apl/pdc_sirec/"
    "perfiles-licitaciones/detalle-licitacion.jsf?idExpediente=1036313"
)
_DESCARGA_JUNTA = (
    "https://www.juntadeandalucia.es/haciendayadministracionpublica/apl/"
    "pdc_sirec_documentacion/rest/descargar/documento/"
)


@pytest.mark.parametrize(
    "url",
    [
        _FICHA_ANDALUCIA,
        # La ficha nueva, a la que la web redirige la vieja.
        "https://www.juntadeandalucia.es/haciendayadministracionpublica/apl/pdc-front-publico/"
        "perfiles-licitaciones/detalle-licitacion?idExpediente=1036313",
    ],
)
def test_id_expediente_de_la_ficha_vieja_y_de_la_nueva(url):
    assert dp.id_expediente_andalucia(url) == "1036313"


@pytest.mark.parametrize(
    "url",
    [
        None,
        "https://www.juntadeandalucia.es/temas/contratacion-publica.html",
        "https://www.juntadeandalucia.es/x/detalle-licitacion.jsf?idExpediente=1036313/../1",
        "https://www.juntadeandalucia.es/x/detalle-licitacion.jsf?idExpediente=1&idExpediente=2",
        "https://evil.example/x/detalle-licitacion.jsf?idExpediente=1036313",
    ],
)
def test_sin_ficha_de_la_junta_no_hay_expediente(url):
    assert dp.id_expediente_andalucia(url) is None


def test_detalle_andalucia_mapea_las_categorias_y_usa_el_sha256_como_identidad():
    crudo = json.loads(_FIXTURE_ANDALUCIA.read_text("utf-8"))
    documentos = dp.parse_detalle_andalucia(crudo)

    assert [(d.tipo, d.uri, d.filename) for d in documentos] == [
        (
            "legal",
            f"{_DESCARGA_JUNTA}441311",
            "PCAP - Pliegos de Cláusulas Administrativas Particulares",
        ),
        ("technical", f"{_DESCARGA_JUNTA}441224", "PPT - Pliego de prescripciones técnicas"),
        ("legal", f"{_DESCARGA_JUNTA}441227", "DEUC"),
    ]
    publicados = crudo["hits"]["hits"][0]["_source"]["documentos"]
    assert [d.source_hash for d in documentos] == [doc["sha256"] for doc in publicados]


def test_detalle_andalucia_solo_trae_pliegos_activos_con_forma_valida():
    """Ni versiones sustituidas, ni actas ni adjudicación, ni un id o hash que compondría otra ruta."""
    huella = "a" * 64

    def doc(**campos: Any) -> dict[str, Any]:
        return {"id": 7, "categoria": "Documento adicional", "nombre": "Anexo I", "sha256": huella,
                "estado": "Activo", **campos}  # fmt: skip

    datos = {"hits": {"hits": [{"_source": {"documentos": [
        doc(),
        doc(id=8, estado="Inactivo"),
        doc(id=9, categoria="Acta de la mesa de contratación"),
        doc(id=10, categoria="Resolución de adjudicación"),
        doc(id="11/../12"),
        doc(id=13, sha256="no-es-un-hash"),
        doc(),  # repetido: un solo documento
    ]}}]}}  # fmt: skip

    assert [(d.tipo, d.uri) for d in dp.parse_detalle_andalucia(datos)] == [
        ("additional", f"{_DESCARGA_JUNTA}7")
    ]


@pytest.mark.parametrize("datos", [{}, {"hits": {"hits": []}}, {"hits": {"hits": [{}, {}]}}, None])
def test_detalle_andalucia_sin_un_expediente_no_falla(datos):
    assert dp.parse_detalle_andalucia(datos) == []


def test_documentos_de_andalucia_pide_el_expediente_como_lo_pide_su_web():
    pedidas: list[tuple[str, Any]] = []

    def obtener(url: str, cuerpo: bytes) -> bytes:
        pedidas.append((url, json.loads(cuerpo)))
        return _FIXTURE_ANDALUCIA.read_bytes()

    documentos = dp.documentos_de_andalucia(_FICHA_ANDALUCIA, obtener=obtener)

    assert pedidas == [(dp._API_ANDALUCIA, {"query": {"match": {"_id": "1036313"}}})]
    assert documentos is not None and len(documentos) == 3


def test_documentos_de_andalucia_no_pide_nada_si_la_url_no_es_su_ficha():
    def obtener(url: str, cuerpo: bytes) -> bytes:
        raise AssertionError("no debía pedir nada")

    assert dp.documentos_de_andalucia("https://ted.europa.eu/x", obtener=obtener) is None


class _RepoFalso:
    def __init__(self, filas: list[dict[str, Any]]) -> None:
        self.filas = filas
        self.escritos: dict[str, list[DocumentoReferencia]] = {}
        #: Llamadas a ``upsert_meta_batch``; las filas de ``fallan`` no se escriben.
        self.lotes = 0
        self.fallan: set[str] = set()

    def pscp_para_documentos(
        self, limit: int = 200, *, dias_cambio: int | None = 7
    ) -> list[dict[str, Any]]:
        return self.filas[:limit]

    def ted_vigentes_sin_documentos(self, limit: int = 300) -> list[str]:
        return [f["id_externo"] for f in self.filas][:limit]

    def andalucia_para_documentos(self, limit: int = 60) -> list[dict[str, Any]]:
        return self.filas[:limit]

    def upsert_meta(self, licitacion_id: str, refs: list[DocumentoReferencia]) -> int:
        self.escritos[licitacion_id] = refs
        return len(refs)

    def upsert_meta_batch(
        self, docs_por_lic: dict[str, list[DocumentoReferencia]]
    ) -> dict[str, Exception]:
        self.lotes += 1
        for lic, refs in docs_por_lic.items():
            if lic not in self.fallan:
                self.escritos[lic] = refs
        return {lic: RuntimeError("roto") for lic in docs_por_lic if lic in self.fallan}


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


def test_si_no_llega_la_ficha_del_anuncio_cuenta_como_fallo_y_no_escribe(repo_falso):
    repo = repo_falso([{"id_externo": "pscp:cerrada", "url": _FICHA_CERRADA}])

    def obtener(url: str) -> bytes:
        if url.endswith("/300719618"):
            raise ConnectionError("plataforma caída")
        return _FIXTURE_FORMALITZACIO.read_bytes()

    resumen = dp.completar_documentos_pscp(pausa_s=0, obtener=obtener)

    assert (resumen.candidatas, resumen.fallidas, repo.escritos) == (1, 1, {})


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
    assert repo.lotes == 1  # una escritura para todas, no una por fila


def test_completar_ted_cuenta_la_fila_que_no_se_pudo_escribir(repo_falso):
    repo = repo_falso([{"id_externo": "ted:1-2026"}, {"id_externo": "ted:2-2026"}])
    repo.fallan = {"ted:2-2026"}

    resumen = dp.completar_documentos_ted()

    assert set(repo.escritos) == {"ted:1-2026"}
    assert (resumen.con_documentos, resumen.referencias, resumen.fallidas) == (1, 1, 1)
    assert resumen.errores == ["ted:2-2026: roto"]


def test_completar_andalucia_escribe_los_pliegos_de_cada_vigente(repo_falso):
    repo = repo_falso(
        [
            {"id_externo": "placsp_agregadas:EICE21:EXPT26-00040", "url": _FICHA_ANDALUCIA},
            {"id_externo": "placsp_agregadas:X:sin-ficha", "url": "https://otra.example/"},
        ]
    )

    resumen = dp.completar_documentos_andalucia(
        pausa_s=0, obtener=lambda url, cuerpo: _FIXTURE_ANDALUCIA.read_bytes()
    )

    assert len(repo.escritos["placsp_agregadas:EICE21:EXPT26-00040"]) == 3
    assert set(repo.escritos) == {"placsp_agregadas:EICE21:EXPT26-00040"}
    assert (resumen.candidatas, resumen.con_documentos, resumen.referencias) == (2, 1, 3)


def test_completar_andalucia_corta_tras_cinco_fallos_seguidos(repo_falso):
    repo_falso([{"id_externo": f"a:{i}", "url": _FICHA_ANDALUCIA} for i in range(20)])
    pedidas = 0

    def caida(url: str, cuerpo: bytes) -> bytes:
        nonlocal pedidas
        pedidas += 1
        raise ConnectionError("plataforma caída")

    resumen = dp.completar_documentos_andalucia(pausa_s=0, obtener=caida)

    assert (pedidas, resumen.fallidas) == (5, 5)


def test_completar_andalucia_no_deja_que_una_peticion_pase_del_presupuesto(repo_falso, monkeypatch):
    repo_falso([{"id_externo": f"a:{i}", "url": _FICHA_ANDALUCIA} for i in range(2)])
    instantes = iter([100.0, 100.0, 100.0, 108.0, 108.0])
    topes: list[float] = []

    def obtener(
        url: str, *, host: str, timeout_s: float | None = None, cuerpo: Any = None
    ) -> bytes:
        assert (host, json.loads(cuerpo)) == (
            "www.juntadeandalucia.es",
            {"query": {"match": {"_id": "1036313"}}},
        )
        topes.append(float(timeout_s or 0))
        return _FIXTURE_ANDALUCIA.read_bytes()

    monkeypatch.setattr(dp, "_obtener", obtener)

    resumen = dp.completar_documentos_andalucia(
        presupuesto_s=10, pausa_s=0, reloj=lambda: next(instantes)
    )

    assert resumen.candidatas == 2
    assert topes == [10.0, 2.0]


# ── Conectores y runner ──────────────────────────────────────────────────────


def test_ted_reempareja_antes_de_dar_anuncios_y_un_fallo_no_salta_el_otro(monkeypatch):
    from scraper.connectors.ted import TedConnector

    orden: list[str] = []

    def reemparejar() -> Any:
        orden.append("reemparejar")
        raise RuntimeError("BD caída")

    def vigentes(self: TedConnector) -> Any:
        orden.append("vigentes")
        raise ConnectionError("API de TED caída")

    def completar() -> dp.ResumenDocumentos:
        orden.append("anuncios")
        return dp.ResumenDocumentos()

    monkeypatch.setattr("services.dedupe.reemparejar_ted_por_id_evl", reemparejar)
    monkeypatch.setattr(TedConnector, "reemparejar_vigentes", vigentes)
    monkeypatch.setattr("scraper.documentos_plataforma.completar_documentos_ted", completar)

    TedConnector().completar_documentos()

    assert orden == ["reemparejar", "vigentes", "anuncios"]


class _RespuestaTed:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _ApiTedReferencias:
    """API de TED que contesta ``publication-number IN (…)`` con los avisos que tiene."""

    def __init__(self, avisos: dict[str, dict[str, Any]]) -> None:
        self.avisos = avisos
        self.pedidos: list[list[str]] = []

    def post(self, url: str, json: dict[str, Any], timeout: float) -> _RespuestaTed:
        numeros = json["query"].removeprefix("publication-number IN (").removesuffix(")").split()
        self.pedidos.append(numeros)
        return _RespuestaTed({"notices": [self.avisos[n] for n in numeros if n in self.avisos]})


def test_ted_reempareja_las_vigentes_releyendo_sus_referencias(monkeypatch):
    """BT-22 y BT-04 no se guardan: se le piden de nuevo a la API, por lotes."""
    from scraper.connectors import ted

    monkeypatch.setattr(ted, "_PAGE_SIZE", 2)
    monkeypatch.setattr(ted, "_PAGE_PAUSE_S", 0)
    monkeypatch.setattr(
        "db.repositories.dedupe.ted_vigentes_sin_pareja",
        lambda limit: ["ted:111-2026", "ted:222-2026", "ted:333-2026", "ted:mal", "ted:999-2026"],
    )
    api = _ApiTedReferencias(
        {
            "111-2026": {"publication-number": "111-2026", "internal-identifier-proc": "EJIE-1"},
            "222-2026": {"publication-number": "222-2026"},
            "333-2026": {"publication-number": "333-2026", "procedure-identifier": "AB-CD"},
        }
    )
    recibidas: dict[str, ReferenciaCruzada] = {}

    def detectar(*, fuente: str, referencias: dict[str, ReferenciaCruzada]) -> Any:
        assert fuente == "ted"
        recibidas.update(referencias)
        return dp.ResumenDocumentos()

    monkeypatch.setattr("services.dedupe.detect_duplicados_por_referencia", detectar)
    connector = ted.TedConnector(session=api)
    # La pasada ya releyó 999: su referencia se evaluó en el cierre del lote.
    connector._referencias["ted:999-2026"] = ReferenciaCruzada(expediente="X")

    connector.reemparejar_vigentes()

    assert api.pedidos == [["111-2026", "222-2026"], ["333-2026"]]
    assert recibidas == {
        "ted:111-2026": ReferenciaCruzada(expediente="EJIE-1"),
        "ted:333-2026": ReferenciaCruzada(procedimiento="ab-cd"),
    }


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
    monkeypatch.setattr("db.cache_signal.signal_cache_invalidation", lambda: orden.append("cache"))

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


class _ConectorSinFilas:
    """La pasada habitual de PSCP: el dataset no trae nada nuevo desde el cursor."""

    source_id = "pscp"

    def __init__(self, completar: Any) -> None:
        self._completar = completar

    def fetch(self, cursor: Any) -> Any:
        return iter(())

    def parse(self, raw: Any) -> Any:
        raise AssertionError("no hay nada que parsear")

    def new_cursor(self) -> None:
        return None

    def completar_documentos(self) -> None:
        self._completar()


@pytest.fixture()
def runner_sin_bd(monkeypatch):
    """``run_connector`` sin Postgres: el cursor y la salud de la fuente, doblados."""
    from scraper.connectors import base

    monkeypatch.setattr(base, "get_cursor", lambda source_id: None)
    monkeypatch.setattr(base, "record_source_started", lambda source_id: None)
    monkeypatch.setattr(base, "_record_source_completed", lambda result: None)
    return base


def test_sin_filas_nuevas_el_runner_completa_documentos_igual(runner_sin_bd, monkeypatch):
    """El paso lee de la BD las convocatorias vigentes: no depende del lote.

    Hasta el 2026-10-03 colgaba solo de ``_post_ingestion``, que el runner se
    salta cuando no parsea nada. PSCP actualiza su dataset una vez al día, así
    que casi todas sus pasadas son de cero filas: en producción no llegó a leer
    ni una ficha (0 filas PSCP con documentos tras la primera pasada de #395).
    """
    completadas: list[str] = []
    cierres: list[str] = []
    monkeypatch.setattr(runner_sin_bd, "_post_ingestion", lambda *a, **k: cierres.append("x"))

    resultado = runner_sin_bd.run_connector(_ConectorSinFilas(lambda: completadas.append("x")))

    assert (resultado.fetched, resultado.parsed) == (0, 0)
    assert completadas == ["x"]
    # Sin lote no hay empresas que resolver ni filas que deduplicar.
    assert cierres == []


def test_sin_filas_un_completar_roto_no_tumba_la_pasada(runner_sin_bd):
    def roto() -> None:
        raise RuntimeError("plataforma caída")

    resultado = runner_sin_bd.run_connector(_ConectorSinFilas(roto))

    assert resultado.errores == 0
    assert not resultado.fetch_failed


# ── Con lote: el paso de PSCP no espera al cierre del lote ───────────────────


class _CorteDelStep(BaseException):
    """El ``timeout-minutes`` del step: mata el proceso, no es una ``Exception``.

    Hereda de ``BaseException`` a propósito, como ``SystemExit``: nada del
    runner la atrapa, igual que nada sobrevive a que Actions mate el proceso.
    """


class _ConectorConLote:
    """Una pasada con una fila: la que de verdad ocurría el 2026-10-03."""

    def __init__(self, source_id: str, completar: Any, *, primero: bool) -> None:
        self.source_id = source_id
        self._completar = completar
        if primero:
            self.completar_documentos_primero = True

    def fetch(self, cursor: Any) -> Any:
        from scraper.connectors.base import RawNotice

        yield RawNotice(natural_id="1", payload={})

    def parse(self, raw: Any) -> Any:
        from db.upsert import Licitacion
        from scraper.connectors.base import ParsedTender

        return ParsedTender(
            licitacion=Licitacion(
                id_externo=f"{self.source_id}:1",
                titulo="Llicències de programari de gestió documental",
                fuente=self.source_id,
            )
        )

    def new_cursor(self) -> None:
        return None

    def completar_documentos(self) -> None:
        self._completar()


@pytest.fixture()
def runner_con_lote(runner_sin_bd, monkeypatch):
    """``run_connector`` con lote y sin BD: el upsert devuelve una fila nueva."""
    from db.upsert import UpsertResult

    monkeypatch.setattr(
        runner_sin_bd,
        "upsert_licitaciones_with_history",
        lambda lics, source: UpsertResult(
            inserted=[lic.id_externo for lic in lics], modified=[], unchanged=[]
        ),
    )
    return runner_sin_bd


def test_con_lote_pscp_lee_las_fichas_antes_de_que_el_step_corte_el_cierre(
    runner_con_lote, monkeypatch
):
    """La segunda causa del backlog: con filas, el corte llegaba antes que el paso.

    El 2026-10-03 (run 37126368765) el cursor quedó escrito 3 s después de la
    última página y el step murió a los 10 minutos dentro de la resolución de
    empresas, que va primero en ``_post_ingestion``: el paso de documentos,
    detrás de ella y de los dos dedupes, no llegó a correr. El paso no lee nada
    de lo que esos pasos escriben, así que PSCP lo pide **antes**.
    """
    orden: list[str] = []

    def empresas(**kw: Any) -> None:
        orden.append("empresas")
        raise _CorteDelStep

    monkeypatch.setattr("services.entity_resolution.resolve_all_unlinked", empresas)

    conector = _ConectorConLote("pscp", lambda: orden.append("documentos"), primero=True)
    with pytest.raises(_CorteDelStep):
        runner_con_lote.run_connector(conector)

    assert orden == ["documentos", "empresas"]


def test_con_lote_el_paso_primero_no_se_repite_dentro_del_cierre(runner_con_lote, monkeypatch):
    llamadas: list[str] = []
    for paso in (
        "services.entity_resolution.resolve_all_unlinked",
        "services.dedupe.detect_duplicates",
    ):
        monkeypatch.setattr(paso, lambda **kw: None)
    monkeypatch.setattr("services.contract_events.derive_new_events", lambda: None)
    monkeypatch.setattr("db.cache_signal.signal_cache_invalidation", lambda: None)

    conector = _ConectorConLote("pscp", lambda: llamadas.append("x"), primero=True)
    resultado = runner_con_lote.run_connector(conector)

    assert resultado.parsed == 1
    assert llamadas == ["x"]


def test_sin_declararlo_el_paso_sigue_detras_de_los_dedupes(runner_con_lote, monkeypatch):
    """TED y PLACSP no cambian: su paso necesita las marcas que deja el dedupe.

    Un aviso TED recién emparejado lee los pliegos de su canónica, y el paso lo
    sabe por la marca que el dedupe acaba de escribir.
    """
    orden: list[str] = []
    monkeypatch.setattr(
        "services.entity_resolution.resolve_all_unlinked", lambda **kw: orden.append("empresas")
    )
    monkeypatch.setattr("services.dedupe.detect_duplicates", lambda **kw: orden.append("dedupe"))
    monkeypatch.setattr("services.contract_events.derive_new_events", lambda: None)
    monkeypatch.setattr("db.cache_signal.signal_cache_invalidation", lambda: None)

    conector = _ConectorConLote("ted", lambda: orden.append("documentos"), primero=False)
    runner_con_lote.run_connector(conector)

    assert orden == ["empresas", "dedupe", "documentos"]


def test_pscp_y_agregadas_piden_el_paso_de_documentos_antes_del_cierre():
    from scraper.connectors.placsp import PlacspAtomConnector, PlacspBulkConnector
    from scraper.connectors.placsp_agregadas import (
        URL_SINDICACION_1044,
        PlacspAgregadasConnector,
    )
    from scraper.connectors.pscp import PscpConnector
    from scraper.connectors.ted import TedConnector

    for primero in (PscpConnector(), PlacspAgregadasConnector(URL_SINDICACION_1044)):
        assert getattr(primero, "completar_documentos_primero", False) is True
    for otro in (TedConnector(), PlacspAtomConnector(), PlacspBulkConnector(2026, 9)):
        assert not getattr(otro, "completar_documentos_primero", False)


def test_el_conector_de_agregadas_lee_los_pliegos_de_andalucia(monkeypatch):
    from scraper.connectors.placsp_agregadas import (
        URL_SINDICACION_1044,
        PlacspAgregadasConnector,
    )

    llamadas: list[str] = []

    def completar() -> dp.ResumenDocumentos:
        llamadas.append("andalucia")
        return dp.ResumenDocumentos()

    monkeypatch.setattr("scraper.documentos_plataforma.completar_documentos_andalucia", completar)

    PlacspAgregadasConnector(URL_SINDICACION_1044).completar_documentos()

    assert llamadas == ["andalucia"]


def test_el_conector_pscp_acota_el_paso_con_su_presupuesto(monkeypatch):
    from scraper.connectors import pscp

    recibido: dict[str, Any] = {}

    def completar(**kw: Any) -> dp.ResumenDocumentos:
        recibido.update(kw)
        return dp.ResumenDocumentos()

    monkeypatch.setattr("scraper.documentos_plataforma.completar_documentos_pscp", completar)

    pscp.PscpConnector().completar_documentos()

    assert recibido["presupuesto_s"] == pscp.PRESUPUESTO_DOCUMENTOS_S
    # Holgura para la resolución de empresas y los dedupes que vienen detrás,
    # dentro de los 10 minutos del step.
    assert 0 < pscp.PRESUPUESTO_DOCUMENTOS_S <= 180


def test_completar_pscp_no_deja_que_una_peticion_pase_del_presupuesto(repo_falso, monkeypatch):
    """Sin tope por petición, una ficha lenta podía alargar el paso 30 s más.

    El presupuesto se miraba solo **antes** de cada ficha; la petición en curso
    tenía el ``REQUEST_TIMEOUT`` entero (30 s) por delante. Con el reloj al
    borde, cada petición recibe lo que queda, y nunca más que el timeout global.
    """
    repo_falso([{"id_externo": f"pscp:{i}", "url": _FICHA_PSCP} for i in range(2)])
    monkeypatch.setattr(
        "services.dedupe.marcar_republicaciones_ted", lambda *a: RepublicacionesTed()
    )
    # Inicio; y por fila, la comprobación del presupuesto y el tope de su petición.
    instantes = iter([100.0, 100.0, 100.0, 108.0, 108.0])
    topes: list[float] = []

    def obtener(url: str, *, host: str, timeout_s: float | None = None) -> bytes:
        assert host == "contractaciopublica.cat"
        topes.append(float(timeout_s or 0))
        return _FIXTURE_PSCP.read_bytes()

    monkeypatch.setattr(dp, "_obtener", obtener)

    resumen = dp.completar_documentos_pscp(
        presupuesto_s=10, pausa_s=0, reloj=lambda: next(instantes)
    )

    assert resumen.candidatas == 2
    assert topes == [10.0, 2.0]


def test_la_ficha_del_anuncio_solo_tiene_lo_que_dejo_la_primera(repo_falso, monkeypatch):
    """Un expediente cerrado pide dos fichas; el tope de la segunda descuenta la primera."""
    repo_falso([{"id_externo": "pscp:cerrada", "url": _FICHA_CERRADA}])
    instantes = iter([100.0, 100.0, 100.0, 107.0])
    topes: list[float] = []
    por_publicacion = {"300751065": _FIXTURE_FORMALITZACIO, "300719618": _FIXTURE_ANUNCI}

    def obtener(url: str, *, host: str, timeout_s: float | None = None) -> bytes:
        topes.append(float(timeout_s or 0))
        return por_publicacion[url.rsplit("/", 1)[-1]].read_bytes()

    monkeypatch.setattr(dp, "_obtener", obtener)

    resumen = dp.completar_documentos_pscp(
        presupuesto_s=10, pausa_s=0, reloj=lambda: next(instantes)
    )

    assert topes == [10.0, 3.0]
    assert (resumen.con_documentos, resumen.referencias) == (1, 4)


# ── Red: un circuito por plataforma ──────────────────────────────────────────


@pytest.mark.parametrize(
    ("host", "nombre"),
    [
        ("ted.europa.eu", "ted"),
        ("contractaciopublica.cat", "pscp"),
        ("www.juntadeandalucia.es", "andalucia"),
        ("www.contratacion.euskadi.eus", "euskadi"),
        ("contratos-publicos.comunidad.madrid", "madrid"),
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


def test_integration_ted_vigentes_sin_pareja(db) -> None:
    """Lo que re-empareja cada pasada: vigentes sin pareja decidida, tengan o no el anuncio."""
    from db.database import connect
    from db.repositories import dedupe as dedupe_repo

    def marcar(c: Any, ted: str, status: str, *, resuelta: bool = False) -> None:
        c.execute(
            "INSERT INTO licitaciones_duplicados (licitacion_id, canonical_id, clave_match, "
            " confianza, status, resolved_at) VALUES (%s, 'EXP-CANON', 'x', 1.0, %s, %s)",
            (ted, status, _dia(0) if resuelta else None),
        )

    with connect() as c:
        _insertar(c, "EXP-CANON")
        _insertar(c, "ted:1-2026")  # vigente sin pareja: entra
        _insertar(c, "ted:2-2026")
        _documento(c, "ted:2-2026")  # con el anuncio puesto: entra igual
        _insertar(c, "ted:3-2026")
        marcar(c, "ted:3-2026", "confirmed")
        _insertar(c, "ted:4-2026")
        marcar(c, "ted:4-2026", "pending")  # sin decidir: entra
        _insertar(c, "ted:5-2026")
        marcar(c, "ted:5-2026", "rejected", resuelta=True)  # alguien dijo que no
        _insertar(c, "ted:6-2026", fecha_limite=_dia(-1))
        _insertar(c, "ted:7-2026", estado="RES")

    assert set(dedupe_repo.ted_vigentes_sin_pareja()) == {"ted:1-2026", "ted:2-2026", "ted:4-2026"}


def test_integration_andalucia_para_documentos(db) -> None:
    from db.database import connect
    from db.repositories.documentos import DocumentosRepository

    with connect() as c:
        _insertar(c, "placsp_agregadas:EICE21:SIN-DOCS", url=_FICHA_ANDALUCIA)
        _insertar(c, "placsp_agregadas:EICE21:RECIENTE", url=_FICHA_ANDALUCIA)
        _documento(c, "placsp_agregadas:EICE21:RECIENTE")
        _insertar(
            c, "placsp_agregadas:EICE21:LEIDA", url=_FICHA_ANDALUCIA, fecha_publicacion=_dia(-40)
        )
        _documento(c, "placsp_agregadas:EICE21:LEIDA")
        _insertar(c, "placsp_agregadas:EICE21:ADJ", url=_FICHA_ANDALUCIA, estado="ADJ")
        _insertar(c, "placsp_agregadas:EICE21:VENCIDA", url=_FICHA_ANDALUCIA, fecha_limite=_dia(-1))
        _insertar(
            c, "placsp_agregadas:X:MADRID", url="https://contratos-publicos.comunidad.madrid/x"
        )
        _insertar(c, "placsp:1:EXP", url=_FICHA_ANDALUCIA)
        _insertar(c, "placsp_agregadas:EICE21:DUPLICADA", url=_FICHA_ANDALUCIA)
        c.execute(
            "INSERT INTO licitaciones_duplicados (licitacion_id, canonical_id, clave_match, "
            " confianza, status) VALUES ('placsp_agregadas:EICE21:DUPLICADA', 'placsp:1:EXP', "
            " 'x', 1.0, 'confirmed')"
        )

    filas = DocumentosRepository().andalucia_para_documentos()

    assert [f["id_externo"] for f in filas] == [
        "placsp_agregadas:EICE21:SIN-DOCS",
        "placsp_agregadas:EICE21:RECIENTE",
    ]


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


def _sembrar_pscp() -> None:
    """Convocatorias vigentes y expedientes ya cerrados de la PSCP."""
    from db.database import connect

    tic = {"analysis_universe": "pscp_observed", "tecnologia": "SAP"}

    def cambio(dias: int) -> str:
        """``fecha_actualizacion_fuente`` como la escribe Socrata."""
        return f"{_dia(dias)}T09:00:15.740Z"

    with connect() as c:
        _insertar(c, "pscp:SIN-DOCS", **tic)
        _insertar(c, "pscp:RECIENTE", **tic)
        _documento(c, "pscp:RECIENTE")
        _insertar(c, "pscp:YA-LEIDA", **tic, fecha_publicacion=_dia(-40))
        _documento(c, "pscp:YA-LEIDA")
        _insertar(c, "pscp:LIMPIEZA", analysis_universe="pscp_observed", tecnologia=None)
        # Solo por CPV 48/72: no se publica, pero su anuncio TED sí.
        _insertar(
            c,
            "pscp:SOLO-CPV",
            analysis_universe="pscp_observed",
            inclusion_reason="cpv_ti_universe",
        )
        # Cerradas: la ficha guarda su última fase, y los pliegos están en la del anuncio.
        _insertar(c, "pscp:CERRADA", **tic, estado="ADJ")  # sin cambio que fechar
        _insertar(c, "pscp:RESUELTA", **tic, estado="RES", fecha_actualizacion_fuente=cambio(-1))
        _insertar(
            c,
            "pscp:VENCIDA",
            **tic,
            fecha_limite=_dia(-5),
            fecha_actualizacion_fuente=cambio(-2),
        )
        _insertar(c, "pscp:LEIDA", **tic, estado="RES", fecha_actualizacion_fuente=cambio(-1))
        _documento(c, "pscp:LEIDA")
        _insertar(c, "pscp:AGREGADA", **tic, estado="AGR", fecha_actualizacion_fuente=cambio(-1))
        _insertar(c, "pscp:VIEJA", **tic, estado="RES", fecha_actualizacion_fuente=cambio(-30))
        _insertar(c, "pscp:SIN-ESTADO", **tic, estado=None, fecha_actualizacion_fuente=cambio(-3))
        # Republicación de una agregada de PLACSP: su ficha lee los pliegos de la canónica.
        _insertar(c, "placsp_agregadas:1:X", **tic, estado="ADJ")
        _insertar(c, "pscp:DUPLICADA", **tic, estado="ADJ", fecha_actualizacion_fuente=cambio(-1))
        c.execute(
            "INSERT INTO licitaciones_duplicados (licitacion_id, canonical_id, clave_match, "
            " confianza, status) VALUES ('pscp:DUPLICADA', 'placsp_agregadas:1:X', 'x', 1.0, "
            " 'confirmed')"
        )


def test_integration_pscp_para_documentos(db) -> None:
    from db.repositories.documentos import DocumentosRepository

    _sembrar_pscp()

    filas = DocumentosRepository().pscp_para_documentos()

    # Las vigentes delante (sin documentos primero), para que un retoque masivo del
    # dataset no deje sin presupuesto su refresco; las cerradas, solo si cambiaron
    # en la última semana. La vigente leída hace 40 días no se vuelve a pedir.
    assert [f["id_externo"] for f in filas] == [
        "pscp:SIN-DOCS",
        "pscp:SOLO-CPV",
        "pscp:RECIENTE",
        "pscp:RESUELTA",
        "pscp:VENCIDA",
        "pscp:SIN-ESTADO",
    ]


def test_integration_el_barrido_lee_todas_las_cerradas_sin_documentos(db) -> None:
    from db.repositories.documentos import DocumentosRepository

    _sembrar_pscp()

    filas = DocumentosRepository().pscp_para_documentos(dias_cambio=None)

    assert [f["id_externo"] for f in filas] == [
        "pscp:SIN-DOCS",
        "pscp:SOLO-CPV",
        "pscp:RECIENTE",
        "pscp:RESUELTA",
        "pscp:VENCIDA",
        "pscp:SIN-ESTADO",
        "pscp:VIEJA",
        "pscp:CERRADA",
    ]


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


class _ConectorConUnaFila:
    """Un lote de una fila y un paso de documentos que cuenta sus llamadas."""

    source_id = "fake"

    def __init__(self, notices: list[str]) -> None:
        self.notices = notices
        self.completadas = 0

    def fetch(self, cursor: Any) -> Any:
        from scraper.connectors.base import RawNotice

        for natural_id in self.notices:
            yield RawNotice(natural_id=natural_id, payload={})

    def parse(self, raw: Any) -> Any:
        from db.upsert import Licitacion
        from scraper.connectors.base import ParsedTender

        return ParsedTender(
            licitacion=Licitacion(
                id_externo=f"fake:{raw.natural_id}",
                titulo="Suministro de licencias de software de gestión documental",
                fuente="fake",
                fecha_publicacion=_dia(-1),
            )
        )

    def new_cursor(self) -> None:
        return None

    def completar_documentos(self) -> None:
        self.completadas += 1


@pytest.mark.parametrize("notices", [["A"], []], ids=["con_lote", "sin_lote"])
def test_integration_el_paso_de_documentos_corre_una_vez_por_pasada(db, notices) -> None:
    """Con lote va dentro de ``_post_ingestion``; sin lote, directo. Nunca dos veces."""
    from scraper.connectors.base import run_connector

    conector = _ConectorConUnaFila(notices)

    resultado = run_connector(conector)

    assert resultado.parsed == len(notices)
    assert conector.completadas == 1
